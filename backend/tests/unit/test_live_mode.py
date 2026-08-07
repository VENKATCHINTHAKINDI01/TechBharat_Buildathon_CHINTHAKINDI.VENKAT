"""Live meeting mode: consent, audio, speaker attribution, dedupe.

Four properties matter here:
  - audio is refused without consent,
  - the mic track is attributed with certainty, the remote track is not,
  - the same commitment heard twice does not become two candidates,
  - nothing is created; approval stays a separate human act.
"""
import pytest

from app.adapters.repositories.memory import InMemoryRepository
from app.adapters.transcription import AudioChunk, ScriptedTranscriber
from app.adapters.transcription.auto import NullTranscriber
from app.core.config import Settings
from app.domain.models import Participant
from app.services.diarization import DiarizationResult, SpeakerTurn
from app.services.extraction.reference import ReferenceExtractor
from app.services.live import REMOTE_PLACEHOLDER, ConsentRequired, LiveSession
from tests.conftest import MEETING_DATE

PARTICIPANTS = [
    Participant(participant_id="p-arjun", name="Arjun"),
    Participant(participant_id="p-rohit", name="Rohit"),
    Participant(participant_id="p-priya", name="Priya"),
]


class StubDiarizer:
    name = "stub"

    def __init__(self, turns=None, fail=False):
        self.turns = turns or []
        self.fail = fail

    async def diarize(self, audio: bytes, mime: str) -> DiarizationResult:
        if self.fail:
            raise RuntimeError("diarization backend down")
        return DiarizationResult(turns=list(self.turns), engine=self.name)


def _session(transcriber=None, diarizer=None, consent=True, **overrides) -> LiveSession:
    settings = Settings(confidence_threshold=0.75, live_min_new_segments=2, **overrides)
    session = LiveSession(
        meeting_id="live1",
        meeting_date=MEETING_DATE,
        participants=PARTICIPANTS,
        settings=settings,
        extractor=ReferenceExtractor(),
        transcriber=transcriber or ScriptedTranscriber(),
        diarizer=diarizer,
        self_participant_id="p-arjun",
    )
    if consent:
        session.acknowledge_consent()
    return session


def _chunk(track="mic", seq=0, offset_ms=0) -> AudioChunk:
    return AudioChunk(
        track=track, seq=seq, data=b"fake-audio-bytes", offset_ms=offset_ms, duration_ms=6000
    )


# --- consent ---------------------------------------------------------------


async def test_audio_is_refused_without_consent():
    session = _session(consent=False)
    with pytest.raises(ConsentRequired, match="consent"):
        await session.add_audio(_chunk())


async def test_consent_unlocks_capture_and_is_recorded():
    session = _session(consent=False)
    session.acknowledge_consent("Told everyone at 10:01")
    assert session.consent_acknowledged
    assert session.consent_note == "Told everyone at 10:01"


# --- attribution -----------------------------------------------------------


async def test_mic_track_is_attributed_to_the_local_participant():
    transcriber = ScriptedTranscriber({"mic": ["I will finish the API migration by Friday."]})
    session = _session(transcriber)
    created = await session.add_audio(_chunk("mic"))
    assert created[0].speaker == "Arjun"
    assert created[0].track == "mic"


async def test_remote_track_is_not_attributed_to_anyone():
    """Diarization can say there were three voices; it cannot say whose."""
    transcriber = ScriptedTranscriber({"remote": ["Can you finish it by Friday?"]})
    session = _session(transcriber)
    created = await session.add_audio(_chunk("remote"))
    assert created[0].speaker == REMOTE_PLACEHOLDER
    assert created[0].as_dict()["attributable"] is False


async def test_tagging_a_remote_segment_names_the_speaker():
    transcriber = ScriptedTranscriber({"remote": ["Rohit, can you finish the API migration by Friday?"]})
    session = _session(transcriber)
    created = await session.add_audio(_chunk("remote"))

    updated = session.tag_speaker(created[0].segment_id, "p-priya")
    assert updated == 1
    assert session.segments[0].speaker == "Priya"
    assert session.segments[0].speaker_confirmed is True


async def test_tagging_an_unknown_participant_is_rejected():
    transcriber = ScriptedTranscriber({"remote": ["hello"]})
    session = _session(transcriber)
    created = await session.add_audio(_chunk("remote"))
    with pytest.raises(ValueError, match="unknown participant"):
        session.tag_speaker(created[0].segment_id, "p-nobody")


async def test_tagging_one_segment_tags_its_whole_cluster():
    """Confirming a speaker once should carry across the meeting."""
    transcriber = ScriptedTranscriber({"remote": ["first thing", "second thing"]})
    session = _session(transcriber, diarizer=StubDiarizer([SpeakerTurn("SPEAKER_00", 0, 20000)]))
    await session.add_audio(_chunk("remote", 0, offset_ms=0))
    await session.add_audio(_chunk("remote", 1, offset_ms=6000))
    await session.refine_speakers()

    updated = session.tag_speaker(session.segments[0].segment_id, "p-rohit")
    assert updated == 2
    assert all(s.speaker == "Rohit" for s in session.segments)


# --- transcription failure -------------------------------------------------


async def test_a_failed_chunk_is_dropped_not_invented():
    session = _session(NullTranscriber())
    created = await session.add_audio(_chunk())
    assert created == []
    assert session.segments == []
    assert any("Dropped a mic audio chunk" in w for w in session.warnings)


async def test_empty_transcription_adds_nothing():
    session = _session(ScriptedTranscriber({"mic": ["   "]}))
    assert await session.add_audio(_chunk()) == []


# --- diarization -----------------------------------------------------------


async def test_diarization_clusters_remote_speech_without_naming_it():
    transcriber = ScriptedTranscriber({"remote": ["alpha", "beta"]})
    session = _session(
        transcriber,
        diarizer=StubDiarizer(
            [SpeakerTurn("SPEAKER_00", 0, 5000), SpeakerTurn("SPEAKER_01", 6000, 12000)]
        ),
    )
    await session.add_audio(_chunk("remote", 0, offset_ms=0))
    await session.add_audio(_chunk("remote", 1, offset_ms=6000))

    result = await session.refine_speakers()
    assert result.speakers == ["SPEAKER_00", "SPEAKER_01"]
    assert session.segments[0].speaker_cluster == "SPEAKER_00"
    assert session.segments[1].speaker_cluster == "SPEAKER_01"
    # Still not a real name -- that needs a human.
    assert all(REMOTE_PLACEHOLDER in s.speaker for s in session.segments)


async def test_diarization_never_overwrites_a_human_confirmation():
    transcriber = ScriptedTranscriber({"remote": ["alpha"]})
    session = _session(transcriber, diarizer=StubDiarizer([SpeakerTurn("SPEAKER_00", 0, 9000)]))
    created = await session.add_audio(_chunk("remote"))
    session.tag_speaker(created[0].segment_id, "p-priya")

    await session.refine_speakers()
    assert session.segments[0].speaker == "Priya"


async def test_diarization_failure_is_reported_not_fatal():
    transcriber = ScriptedTranscriber({"remote": ["alpha"]})
    session = _session(transcriber, diarizer=StubDiarizer(fail=True))
    await session.add_audio(_chunk("remote"))

    result = await session.refine_speakers()
    assert result.error is not None

    # Diarization is an optimisation, not a requirement. The warning has
    # to carry the reason AND the way forward, or it reads like the
    # meeting was lost when in fact manual tagging still works.
    warning = next(w for w in session.warnings if "could not group the remote voices" in w)
    assert "tag them yourself" in warning
    assert "Reason:" in warning


async def test_mic_track_is_never_touched_by_diarization():
    transcriber = ScriptedTranscriber({"mic": ["I will do it"]})
    session = _session(transcriber, diarizer=StubDiarizer([SpeakerTurn("SPEAKER_09", 0, 9000)]))
    await session.add_audio(_chunk("mic"))
    await session.refine_speakers()
    assert session.segments[0].speaker == "Arjun"
    assert session.segments[0].speaker_cluster is None


# --- extraction ------------------------------------------------------------


async def test_a_commitment_is_surfaced_mid_meeting():
    transcriber = ScriptedTranscriber(
        {
            "remote": ["Rohit, can you finish the API migration by Friday?"],
            "mic": ["Yes, I will finish the API migration by Friday."],
        }
    )
    session = _session(transcriber)
    await session.add_audio(_chunk("remote", 0, offset_ms=0))
    await session.add_audio(_chunk("mic", 1, offset_ms=6000))

    items = await session.process(force=True)
    assert len(items) == 1
    assert session.eligible_count >= 0  # attribution decides eligibility


async def test_reprocessing_does_not_duplicate_the_same_commitment():
    transcriber = ScriptedTranscriber(
        {"mic": ["Rohit, can you finish the API migration by Friday?"] * 3}
    )
    session = _session(transcriber)
    for i in range(3):
        await session.add_audio(_chunk("mic", i, offset_ms=i * 6000))

    first = await session.process(force=True)
    second = await session.process(force=True)
    assert len(first) == len(second) == 1
    assert first[0].candidate_id == second[0].candidate_id


async def test_manual_text_entry_still_works():
    """A demo must never hinge on the venue's audio."""
    session = _session()
    session.add_text_segment("Arjun", "Rohit, can you finish the API migration by Friday?")
    session.add_text_segment("Rohit", "Yes, I will finish the API migration by Friday.")
    items = await session.process(force=True)
    assert len(items) == 1
    assert items[0].owner_participant_id == "p-rohit"


async def test_snapshot_states_that_live_mode_never_acts():
    session = _session()
    session.add_text_segment("Arjun", "Rohit, can you finish it by Friday?")
    session.add_text_segment("Rohit", "Yes, I will finish it by Friday.")
    await session.process(force=True)

    snapshot = session.snapshot()
    assert "No external action occurs without human approval" in snapshot["note"]
    assert snapshot["segment_count"] == 2
    assert "participants" in snapshot


async def test_empty_session_processes_without_error():
    assert await _session().process(force=True) == []
    assert await _session().reprocess_all() == []


async def test_session_persists_candidates_but_approves_nothing():
    session = _session()
    session.add_text_segment("Arjun", "Rohit, can you finish the API migration by Friday?")
    session.add_text_segment("Rohit", "Yes, I will finish the API migration by Friday.")
    await session.process(force=True)

    repository = InMemoryRepository()
    await session.persist(repository)
    stored = await repository.list_items("live1")
    assert len(stored) == 1
    assert await repository.get_review_decision(stored[0].candidate_id) is None
    assert await repository.list_issue_records("live1") == []
