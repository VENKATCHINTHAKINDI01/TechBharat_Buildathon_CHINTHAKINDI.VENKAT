"""End-of-meeting speaker refinement.

During the meeting, speaker attribution is *track-based*: the microphone
is unambiguously you, and the shared meeting tab is "someone else". That
is fast, needs no model, and is never wrong about the one speaker it
claims to know.

What it cannot do is tell three remote voices apart. So when the meeting
ends, the buffered remote-track audio is sent for diarization, which
returns speaker turns (``SPEAKER_00``, ``SPEAKER_01``, …). Those turns
are mapped back onto the already-transcribed segments by **time overlap**
— we never re-transcribe, because that would change the text that
evidence quotes were validated against.

Diarization yields anonymous speaker *clusters*, not names. Turning
``SPEAKER_01`` into "Priya" is a human judgement, so the result is
surfaced as a suggested grouping the reviewer confirms. An unconfirmed
cluster resolves to no owner, and the safety gate blocks the item — which
is the correct outcome, not a bug.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

import httpx

from app.adapters.transcription.convert import convert_to_wav
from app.adapters.transcription.languages import normalize_language_code
from app.core.config import Settings, get_settings

logger = logging.getLogger("nexvi_meets.diarization")


@dataclass
class SpeakerTurn:
    """One contiguous stretch of one anonymous speaker."""

    speaker: str
    start_ms: int
    end_ms: int

    def overlap_ms(self, start_ms: int, end_ms: int) -> int:
        return max(0, min(self.end_ms, end_ms) - max(self.start_ms, start_ms))


@dataclass
class DiarizationResult:
    turns: list[SpeakerTurn] = field(default_factory=list)
    engine: str = "none"
    error: Optional[str] = None

    @property
    def speakers(self) -> list[str]:
        return sorted({t.speaker for t in self.turns})


class DiarizationError(RuntimeError):
    pass


@runtime_checkable
class Diarizer(Protocol):
    name: str

    async def diarize(self, audio: bytes, mime: str) -> DiarizationResult: ...


def assign_speakers(
    segments: list, turns: list[SpeakerTurn], only_track: str = "remote"
) -> dict[str, str]:
    """Map each segment to the speaker cluster it overlaps most.

    Returns ``{segment_id: speaker_cluster}``. Only segments on
    ``only_track`` are considered — the microphone track is already
    attributed with certainty and must not be overwritten by a model's
    guess.

    A segment with no overlapping turn is left unassigned rather than
    given the nearest speaker. Guessing here would silently attach a
    commitment to the wrong person, which is exactly the failure the
    whole product exists to prevent.
    """
    assignments: dict[str, str] = {}
    if not turns:
        return assignments

    for segment in segments:
        if getattr(segment, "track", None) != only_track:
            continue
        start = getattr(segment, "start_ms", None)
        end = getattr(segment, "end_ms", None)
        if start is None or end is None:
            continue

        best_speaker, best_overlap = None, 0
        for turn in turns:
            overlap = turn.overlap_ms(start, end)
            if overlap > best_overlap:
                best_speaker, best_overlap = turn.speaker, overlap

        if best_speaker is not None:
            assignments[segment.segment_id] = best_speaker

    return assignments


class NullDiarizer:
    """Default when no diarization backend is configured.

    Reports honestly that no refinement happened, leaving the track-based
    labels in place.
    """

    name = "none"

    async def diarize(self, audio: bytes, mime: str) -> DiarizationResult:
        return DiarizationResult(engine=self.name, error="No diarization backend configured.")


class SarvamDiarizer:
    """Sarvam's batch speech-to-text with ``with_diarization``.

    Batch only — Sarvam does not offer diarization on its streaming API —
    which is precisely why this runs once at the end rather than during
    the meeting.
    """

    name = "sarvam"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def diarize(self, audio: bytes, mime: str) -> DiarizationResult:
        if not self._settings.sarvam_api_key:
            raise DiarizationError("SARVAM_API_KEY is not set.")
        if not audio:
            return DiarizationResult(engine=self.name, error="no audio buffered")

        # Sarvam rejects audio/webm;codecs=opus — convert to WAV first.
        audio_bytes, audio_mime = convert_to_wav(audio, mime)
        filename = "remote-track.webm" if audio_mime == mime else "remote-track.wav"

        url = f"{self._settings.sarvam_api_base}/speech-to-text"
        headers = {"api-subscription-key": self._settings.sarvam_api_key}
        files = {"file": (filename, audio_bytes, audio_mime)}
        data = {
            "model": self._settings.sarvam_stt_model,
            "language_code": normalize_language_code(self._settings.sarvam_language_code),
            "with_diarization": "true",
        }

        try:
            if self._client is not None:
                response = await self._client.post(url, headers=headers, files=files, data=data)
            else:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(url, headers=headers, files=files, data=data)
        except httpx.HTTPError as exc:
            raise DiarizationError(f"Sarvam diarization request failed: {exc}") from exc

        if response.status_code != 200:
            raise DiarizationError(
                f"Sarvam diarization returned {response.status_code}: {response.text[:300]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise DiarizationError(f"Sarvam returned non-JSON: {exc}") from exc

        return DiarizationResult(turns=parse_sarvam_turns(payload), engine=self.name)


def parse_sarvam_turns(payload: dict) -> list[SpeakerTurn]:
    """Pull speaker turns out of a Sarvam diarization response.

    Tolerant of shape: providers move these keys around between versions,
    and a schema change should degrade to "no refinement" rather than
    crash a meeting that has already been recorded.
    """
    raw_turns = (
        payload.get("diarized_transcript", {}).get("entries")
        or payload.get("entries")
        or payload.get("segments")
        or []
    )
    turns: list[SpeakerTurn] = []
    for entry in raw_turns:
        if not isinstance(entry, dict):
            continue
        speaker = entry.get("speaker_id") or entry.get("speaker")
        if speaker is None:
            continue
        start = entry.get("start_time_seconds", entry.get("start"))
        end = entry.get("end_time_seconds", entry.get("end"))
        if start is None or end is None:
            continue
        try:
            turns.append(
                SpeakerTurn(
                    speaker=str(speaker),
                    start_ms=int(float(start) * 1000),
                    end_ms=int(float(end) * 1000),
                )
            )
        except (TypeError, ValueError):
            continue
    return turns


def build_diarizer(settings: Settings | None = None) -> Diarizer:
    settings = settings or get_settings()
    if settings.sarvam_api_key and settings.live_diarization_enabled:
        return SarvamDiarizer(settings)
    return NullDiarizer()
