"""Speaker-turn mapping. The rule that matters: never guess."""
from dataclasses import dataclass

from app.services.diarization import (
    NullDiarizer,
    SpeakerTurn,
    assign_speakers,
    parse_sarvam_turns,
)


@dataclass
class Seg:
    segment_id: str
    track: str
    start_ms: int
    end_ms: int


def test_overlap_is_measured_not_approximated():
    turn = SpeakerTurn("S0", 1000, 5000)
    assert turn.overlap_ms(2000, 3000) == 1000
    assert turn.overlap_ms(0, 2000) == 1000
    assert turn.overlap_ms(6000, 7000) == 0


def test_a_segment_takes_the_speaker_it_overlaps_most():
    segments = [Seg("s1", "remote", 0, 4000)]
    turns = [SpeakerTurn("S0", 0, 1000), SpeakerTurn("S1", 1000, 4000)]
    assert assign_speakers(segments, turns) == {"s1": "S1"}


def test_a_segment_with_no_overlap_is_left_unassigned():
    """Guessing the nearest speaker would silently attach a commitment to
    the wrong person -- the exact failure this product exists to prevent."""
    segments = [Seg("s1", "remote", 50_000, 55_000)]
    turns = [SpeakerTurn("S0", 0, 1000)]
    assert assign_speakers(segments, turns) == {}


def test_the_mic_track_is_never_reassigned():
    segments = [Seg("mine", "mic", 0, 4000), Seg("theirs", "remote", 0, 4000)]
    turns = [SpeakerTurn("S0", 0, 4000)]
    assert assign_speakers(segments, turns) == {"theirs": "S0"}


def test_no_turns_means_no_assignments():
    assert assign_speakers([Seg("s1", "remote", 0, 1000)], []) == {}


def test_sarvam_turns_are_parsed_from_the_documented_shape():
    payload = {
        "diarized_transcript": {
            "entries": [
                {"speaker_id": "SPEAKER_00", "start_time_seconds": 0.0, "end_time_seconds": 2.5},
                {"speaker_id": "SPEAKER_01", "start_time_seconds": 2.5, "end_time_seconds": 6.0},
            ]
        }
    }
    turns = parse_sarvam_turns(payload)
    assert [t.speaker for t in turns] == ["SPEAKER_00", "SPEAKER_01"]
    assert turns[1].start_ms == 2500


def test_an_unexpected_payload_degrades_to_no_refinement():
    """A provider schema change should not crash a meeting already recorded."""
    assert parse_sarvam_turns({"something": "else"}) == []
    assert parse_sarvam_turns({"entries": [{"nope": 1}, "not a dict"]}) == []


async def test_null_diarizer_reports_honestly():
    result = await NullDiarizer().diarize(b"", "audio/webm")
    assert result.turns == []
    assert "No diarization backend" in result.error
