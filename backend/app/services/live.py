"""Live meeting mode — capture, transcribe, attribute, surface.

The shape of a real meeting assistant: audio arrives while people are
still talking, gets transcribed in near-realtime, is attributed to a
speaker, and commitments appear as they are made.

**Consent is required before any audio is accepted.** Recording other
people without their knowledge is unlawful in many jurisdictions, and the
buildathon brief states it outright. ``begin()`` refuses until consent is
acknowledged, and the acknowledgement is written to the audit log with
the meeting.

**Speaker attribution, honestly.** Two tracks arrive: ``mic`` is the
local participant and is attributed with certainty; ``remote`` is the
shared meeting tab and may contain several people. Remote speech is
labelled ``Remote speaker`` until either the reviewer tags it or the
end-of-meeting diarization pass groups it into clusters they confirm.
Unattributed speech still transcribes and still appears — it simply
cannot own an action item, because owner resolution fails closed.

**Nothing is created live.** The session produces candidates and gate
decisions. Every side effect still requires the same human approval
afterwards. A live agent that could act on its own would fail the
brief's "zero unapproved actions" metric by construction.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from app.adapters.transcription.base import (
    AudioChunk,
    Transcriber,
    TranscriptionError,
)
from app.core.config import Settings
from app.domain.models import (
    GateDecision,
    Participant,
    ResolvedItem,
    TranscriptSegment,
)
from app.domain.safety.gate import check_gate
from app.services.diarization import Diarizer, DiarizationResult, assign_speakers
from app.services.extraction.base import (
    EvidenceReport,
    Extractor,
    ExtractionError,
    drop_unsupported_evidence,
)
from app.services.idempotency import compute_dedupe_key
from app.services.resolvers.combine import resolve_validated_items

logger = logging.getLogger("nexvi_meets.live")

REMOTE_PLACEHOLDER = "Remote speaker"


class ConsentRequired(PermissionError):
    """Audio was offered before consent was acknowledged."""


@dataclass
class LiveSegment:
    """A transcribed piece of speech with where and when it came from."""

    segment_id: str
    track: str
    speaker: str
    text: str
    start_ms: int
    end_ms: int
    engine: str = "unknown"
    language: Optional[str] = None
    # Set once diarization groups this segment with other remote speech.
    speaker_cluster: Optional[str] = None
    # True once a human has said who this actually is.
    speaker_confirmed: bool = False

    def to_transcript_segment(self) -> TranscriptSegment:
        return TranscriptSegment(
            segment_id=self.segment_id,
            speaker=self.speaker,
            start_ms=self.start_ms,
            end_ms=self.end_ms,
            text=self.text,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "track": self.track,
            "speaker": self.speaker,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "engine": self.engine,
            "language": self.language,
            "speaker_cluster": self.speaker_cluster,
            "speaker_confirmed": self.speaker_confirmed,
            "attributable": self.speaker != REMOTE_PLACEHOLDER,
        }


class LiveSession:
    def __init__(
        self,
        *,
        meeting_id: str,
        meeting_date: date,
        participants: list[Participant],
        settings: Settings,
        extractor: Extractor,
        transcriber: Transcriber,
        fallback_extractor: Optional[Extractor] = None,
        diarizer: Optional[Diarizer] = None,
        self_participant_id: Optional[str] = None,
    ) -> None:
        self.meeting_id = meeting_id
        self.meeting_date = meeting_date
        self.participants = participants
        self.settings = settings
        self.extractor = extractor
        self.fallback_extractor = fallback_extractor or extractor
        self.transcriber = transcriber
        self.diarizer = diarizer

        # Which participant is holding the microphone.
        self.self_participant_id = self_participant_id or (
            participants[0].participant_id if participants else None
        )

        self.consent_acknowledged = False
        self.consent_note: Optional[str] = None

        # Paused means the browser has stopped its recorders, so no audio
        # is captured at all -- not buffered-and-held. If someone pauses to
        # discuss something private, "we kept recording and transcribed it
        # later" would be a betrayal of what the button appears to do.
        self.paused = False
        self.paused_at_ms: Optional[int] = None
        self.pause_count = 0

        self.segments: list[LiveSegment] = []
        self._window: deque[LiveSegment] = deque(maxlen=settings.live_window_seconds)
        self._since_last_pass = 0
        self._counter = 0

        # Buffered remote audio, concatenated for the diarization pass.
        self._remote_audio: list[bytes] = []
        self._remote_mime = "audio/webm"
        self._buffered_bytes = 0

        self.items_by_key: dict[str, ResolvedItem] = {}
        self.gate_decisions: dict[str, GateDecision] = {}
        self.diarization: Optional[DiarizationResult] = None
        self.warnings: list[str] = []

        # Diagnostics. "0 candidates" must always come with a reason.
        self.extractor_used: str = getattr(extractor, "name", "unknown")
        self.extraction_error: Optional[str] = None
        self.evidence_report: Optional[EvidenceReport] = None

    # --- consent ---------------------------------------------------------

    def acknowledge_consent(self, note: Optional[str] = None) -> None:
        self.consent_acknowledged = True
        self.consent_note = note or "Participants informed that the meeting is being captured."

    # --- recording control ----------------------------------------------

    def pause(self) -> None:
        if self.paused:
            return
        self.paused = True
        self.pause_count += 1
        self.paused_at_ms = self.segments[-1].end_ms if self.segments else 0

    def resume(self) -> LiveSegment | None:
        """Resume, leaving a visible gap in the transcript.

        The marker matters: a transcript that silently jumps four minutes
        looks like the tool missed something. Saying "paused, nothing
        captured" makes the record honest about its own gaps.
        """
        if not self.paused:
            return None
        self.paused = False
        if self.paused_at_ms is None:
            return None

        marker = LiveSegment(
            segment_id=f"{self.meeting_id}-P{self.pause_count:02d}",
            track="marker",
            speaker="Naina",
            text="— recording paused · nothing was captured —",
            start_ms=self.paused_at_ms,
            end_ms=self.paused_at_ms,
            engine="marker",
            speaker_confirmed=True,
        )
        self.segments.append(marker)
        self.paused_at_ms = None
        return marker

    def _require_consent(self) -> None:
        if not self.consent_acknowledged:
            raise ConsentRequired(
                "Audio capture requires an explicit consent acknowledgement. "
                "Confirm that everyone in the meeting knows it is being recorded."
            )

    # --- speaker naming --------------------------------------------------

    def _participant(self, participant_id: Optional[str]) -> Optional[Participant]:
        return next(
            (p for p in self.participants if p.participant_id == participant_id), None
        )

    def _speaker_for_track(self, track: str) -> str:
        if track == "mic":
            owner = self._participant(self.self_participant_id)
            return owner.name if owner else "You"
        return REMOTE_PLACEHOLDER

    # --- ingestion -------------------------------------------------------

    async def add_audio(self, chunk: AudioChunk) -> list[LiveSegment]:
        """Transcribe one chunk and append the resulting segments.

        A failed chunk is dropped with a warning rather than substituted:
        six lost seconds are recoverable, invented words are not.
        """
        self._require_consent()
        if self.paused:
            # A late chunk from a recorder that had not stopped yet.
            # Dropping it is the whole point of pause.
            return []

        if chunk.track == "remote" and self.settings.live_keep_audio:
            self._buffer_remote(chunk)

        try:
            result = await self.transcriber.transcribe(chunk)
        except TranscriptionError as exc:
            message = f"Dropped a {chunk.track} audio chunk: {exc}"
            logger.warning(message)
            self._warn(message)
            return []

        if result.is_empty:
            return []

        speaker = self._speaker_for_track(chunk.track)
        created: list[LiveSegment] = []
        for span in result.spans:
            text = span.text.strip()
            if not text:
                continue
            segment = LiveSegment(
                segment_id=f"{self.meeting_id}-L{self._counter:04d}",
                track=chunk.track,
                speaker=speaker,
                text=text,
                start_ms=span.start_ms,
                end_ms=span.end_ms or (span.start_ms + chunk.duration_ms),
                engine=result.engine,
                language=result.language,
            )
            self._counter += 1
            self.segments.append(segment)
            self._window.append(segment)
            self._since_last_pass += 1
            created.append(segment)

        # Keep the timeline honest: the two tracks arrive independently.
        self.segments.sort(key=lambda s: s.start_ms)
        return created

    def _buffer_remote(self, chunk: AudioChunk) -> None:
        cap = self.settings.live_max_buffered_mb * 1024 * 1024
        if self._buffered_bytes + len(chunk.data) > cap:
            warning = (
                f"Audio buffer hit {self.settings.live_max_buffered_mb}MB; "
                "diarization will cover only the earlier part of the meeting."
            )
            self._warn(warning)
            return
        self._remote_audio.append(chunk.data)
        self._remote_mime = chunk.mime
        self._buffered_bytes += len(chunk.data)

    def add_text_segment(self, speaker: str, text: str, duration_ms: int = 3000) -> LiveSegment:
        """Manual entry — a typed line, or a demo without a microphone.

        Kept because a demo should never hinge on a venue's audio, and
        because a note-taker may want to add something that was said off
        mic.
        """
        start = self.segments[-1].end_ms if self.segments else 0
        segment = LiveSegment(
            segment_id=f"{self.meeting_id}-L{self._counter:04d}",
            track="manual",
            speaker=speaker.strip() or REMOTE_PLACEHOLDER,
            text=text.strip(),
            start_ms=start,
            end_ms=start + duration_ms,
            engine="manual",
            speaker_confirmed=True,
        )
        self._counter += 1
        self.segments.append(segment)
        self._window.append(segment)
        self._since_last_pass += 1
        return segment

    # --- speaker tagging -------------------------------------------------

    def tag_speaker(self, segment_id: str, participant_id: str) -> int:
        """A human says who a remote segment actually was.

        Tagging one segment tags every segment in the same diarization
        cluster, so confirming a speaker once carries across the meeting.
        Returns the number of segments updated.
        """
        participant = self._participant(participant_id)
        if participant is None:
            raise ValueError(f"unknown participant: {participant_id}")

        target = next((s for s in self.segments if s.segment_id == segment_id), None)
        if target is None:
            raise ValueError(f"unknown segment: {segment_id}")

        cluster = target.speaker_cluster
        updated = 0
        for segment in self.segments:
            same = segment.segment_id == segment_id or (
                cluster is not None and segment.speaker_cluster == cluster
            )
            if same:
                segment.speaker = participant.name
                segment.speaker_confirmed = True
                updated += 1
        return updated

    # --- diarization -----------------------------------------------------

    async def refine_speakers(self) -> DiarizationResult:
        """Group the remote track into speaker clusters after the meeting.

        Only sets ``speaker_cluster``; it never renames a speaker on its
        own. Diarization knows there were three voices, not whose they
        were, and the difference matters when a name decides who owns
        work.
        """
        if self.diarizer is None or not self._remote_audio:
            self.diarization = DiarizationResult(error="no remote audio buffered")
            return self.diarization

        try:
            result = await self.diarizer.diarize(b"".join(self._remote_audio), self._remote_mime)
        except Exception as exc:  # noqa: BLE001 - refinement is best-effort
            logger.warning("Diarization failed: %s", exc)
            self.diarization = DiarizationResult(error=str(exc))
            self.warnings.append(f"Speaker refinement unavailable: {exc}")
            return self.diarization

        assignments = assign_speakers(self.segments, result.turns, only_track="remote")
        by_id = {s.segment_id: s for s in self.segments}
        for segment_id, cluster in assignments.items():
            segment = by_id.get(segment_id)
            # Never overwrite a speaker a human already confirmed.
            if segment is not None and not segment.speaker_confirmed:
                segment.speaker_cluster = cluster
                segment.speaker = f"{REMOTE_PLACEHOLDER} {cluster}"

        self.diarization = result
        return result

    # --- processing ------------------------------------------------------

    @property
    def should_process(self) -> bool:
        return self._since_last_pass >= self.settings.live_min_new_segments

    # --- extraction, with the failures visible ---------------------------

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def _extract(self, segments: list[TranscriptSegment]) -> list:
        """Run the primary extractor, falling back but never silently.

        The old version swallowed ``ExtractionError`` and fell through to
        the deterministic extractor with no warning and no log entry. On a
        live meeting that produced exactly one symptom -- "No candidates
        were extracted from this transcript" -- which is indistinguishable
        from a quiet meeting. The reason has to reach the operator.
        """
        self.extractor_used = getattr(self.extractor, "name", "unknown")
        try:
            return self.extractor.extract(segments, self.meeting_id)
        except ExtractionError as exc:
            self.extractor_used = getattr(self.fallback_extractor, "name", "reference")
            self.extraction_error = str(exc)
            logger.warning("live extraction fell back to %s: %s", self.extractor_used, exc)
            self._warn(
                f"The AI extractor failed, so Naina fell back to the pattern-based one, "
                f"which finds far less in natural speech. Reason: {exc}"
            )
            try:
                return self.fallback_extractor.extract(segments, self.meeting_id)
            except ExtractionError as fallback_exc:
                logger.error("both extractors failed: %s", fallback_exc)
                self._warn(f"Both extractors failed: {fallback_exc}")
                return []

    def _note_evidence(self, report: EvidenceReport) -> None:
        """Surface citation-check losses.

        A model that paraphrases its quotes loses every action item here,
        which looked identical to finding nothing. Now it says so, and
        names an example.
        """
        summary = report.summary
        if not summary:
            return
        self.evidence_report = report
        detail = f" e.g. {report.examples[0]}" if report.examples else ""
        logger.info("evidence check: %s", summary)
        self._warn(
            f"Evidence check: {summary}. The AI quoted words that are not in the "
            f"transcript, so those items cannot be shown to you.{detail}"
        )

    @property
    def window(self) -> list[LiveSegment]:
        return list(self._window)

    async def process(self, force: bool = False) -> list[ResolvedItem]:
        """Run one extraction pass over the rolling window.

        Returns the full current candidate set, not just new ones: a later
        pass can *revise* an earlier candidate — a commitment that was
        ambiguous at 00:30 may have an owner by 00:45 — and the UI needs
        the corrected version rather than both.
        """
        if not force and not self.should_process:
            return list(self.items_by_key.values())
        if not self._window:
            return []

        self._since_last_pass = 0
        window = [s.to_transcript_segment() for s in self._window]

        candidates = self._extract(window)
        report = EvidenceReport()
        candidates = drop_unsupported_evidence(candidates, window, report)
        self._note_evidence(report)
        resolved = resolve_validated_items(candidates, self.participants, self.meeting_date)

        for item in resolved:
            key = compute_dedupe_key(self.meeting_id, item.owner_participant_id, item.raw_text)
            stable = item.model_copy(update={"candidate_id": f"{self.meeting_id}-{key[:10]}"})
            self.items_by_key[key] = stable
            self.gate_decisions[stable.candidate_id] = check_gate(
                stable, self.settings.confidence_threshold
            )

        return list(self.items_by_key.values())

    async def reprocess_all(self) -> list[ResolvedItem]:
        """Re-extract over the whole meeting after speakers are confirmed.

        Worth the second pass: a segment that said "Remote speaker" during
        the call may now say "Priya", which is the difference between an
        item with no owner and one that can actually be approved.
        """
        if not self.segments:
            return []
        self.items_by_key.clear()
        self.gate_decisions.clear()

        # Markers are Naina's own words about the recording, not anyone's
        # speech. They belong in the stored transcript -- that is the
        # whole point of them -- but feeding them to the extractor would
        # let the tool quote itself as evidence for a commitment.
        full = [s.to_transcript_segment() for s in self.segments if s.track != "marker"]

        candidates = self._extract(full)
        report = EvidenceReport()
        candidates = drop_unsupported_evidence(candidates, full, report)
        self._note_evidence(report)

        # The one case that used to be invisible: real speech went in and
        # nothing came out. Silence is a legitimate answer -- plenty of
        # meetings contain no commitments -- but the operator has to be
        # able to tell it apart from a broken extractor.
        if not candidates and len(full) >= 3:
            self._warn(
                f"No commitments were found in {len(full)} transcript segments "
                f"using the '{self.extractor_used}' extractor. If that seems wrong, "
                "check the audit log for the extraction step."
            )

        for item in resolve_validated_items(candidates, self.participants, self.meeting_date):
            key = compute_dedupe_key(self.meeting_id, item.owner_participant_id, item.raw_text)
            stable = item.model_copy(update={"candidate_id": f"{self.meeting_id}-{key[:10]}"})
            self.items_by_key[key] = stable
            self.gate_decisions[stable.candidate_id] = check_gate(
                stable, self.settings.confidence_threshold
            )
        return list(self.items_by_key.values())

    # --- output ----------------------------------------------------------

    @property
    def eligible_count(self) -> int:
        return sum(1 for d in self.gate_decisions.values() if d.eligible)

    @property
    def unattributed_count(self) -> int:
        return sum(1 for s in self.segments if s.speaker == REMOTE_PLACEHOLDER)

    @property
    def spoken_segments(self) -> list[LiveSegment]:
        """Actual speech, excluding Naina's own recording markers."""
        return [s for s in self.segments if s.track != "marker"]

    def snapshot(self, include_segments: int = 40) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "segment_count": len(self.segments),
            "segments": [s.as_dict() for s in self.segments[-include_segments:]],
            "unattributed": self.unattributed_count,
            "paused": self.paused,
            "extractor": self.extractor_used,
            "extraction_error": self.extraction_error,
            "participants": [
                {"participant_id": p.participant_id, "name": p.name} for p in self.participants
            ],
            "candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "raw_text": item.raw_text,
                    "classification": item.classification.value,
                    "owner_participant_id": item.owner_participant_id,
                    "owner_name": next(
                        (
                            p.name
                            for p in self.participants
                            if p.participant_id == item.owner_participant_id
                        ),
                        None,
                    ),
                    "due_date": item.due_date.isoformat() if item.due_date else None,
                    "priority": item.priority.value,
                    "confidence": item.confidence,
                    "field_confidence": item.field_confidence or {},
                    # The live panel shows the current state rather than
                    # just the text, so a task that has been handed on
                    # mid-meeting reads as unsettled while it still is.
                    "current_state": item.current_state,
                    "was_renegotiated": item.was_renegotiated,
                    "timeline": item.timeline,
                    "evidence": [q.model_dump() for q in item.evidence_quotes],
                    "gate": {
                        "eligible": self.gate_decisions[item.candidate_id].eligible,
                        "reasons": self.gate_decisions[item.candidate_id].reasons,
                    },
                }
                for item in self.items_by_key.values()
            ],
            "eligible": self.eligible_count,
            "diarization": {
                "engine": self.diarization.engine if self.diarization else None,
                "speakers": self.diarization.speakers if self.diarization else [],
                "error": self.diarization.error if self.diarization else None,
            },
            "warnings": self.warnings,
            "note": (
                "Live mode surfaces candidates only. No external action occurs "
                "without human approval after the meeting."
            ),
        }

    async def persist(self, repository) -> None:
        """Save results so the normal review flow can pick them up."""
        items = list(self.items_by_key.values())
        if items:
            await repository.save_items(items)
