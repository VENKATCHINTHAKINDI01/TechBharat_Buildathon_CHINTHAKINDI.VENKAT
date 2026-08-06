"""Language-routed transcription, and the test double.

``AutoTranscriber`` runs Whisper first — it is fast, accepts browser WebM
directly, and reports the language it heard. If that language is Indic
and Sarvam is configured, the same chunk is re-transcribed with Saarika,
whose Indian-language and code-mixed accuracy is materially better.

The router never *invents* a result. If Whisper fails it tries Sarvam; if
both fail it raises, and the live session drops the chunk. Silence is an
honest outcome; a hallucinated sentence would become a transcript
segment, and segments are what evidence quotes are checked against.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.adapters.transcription.base import (
    INDIC_LANGUAGES,
    AudioChunk,
    TranscriptionError,
    TranscriptionResult,
    TranscriptSpan,
    Transcriber,
)
from app.core.config import Settings, get_settings

logger = logging.getLogger("nexvi_meets.transcription")


class AutoTranscriber:
    name = "auto"

    def __init__(
        self,
        primary: Transcriber,
        indic: Optional[Transcriber] = None,
        settings: Settings | None = None,
    ) -> None:
        self._primary = primary
        self._indic = indic
        self._settings = settings or get_settings()

    async def transcribe(self, chunk: AudioChunk) -> TranscriptionResult:
        try:
            result = await self._primary.transcribe(chunk)
        except TranscriptionError as exc:
            if self._indic is None:
                raise
            logger.warning("Primary transcriber failed (%s); trying Sarvam.", exc)
            return await self._indic.transcribe(chunk)

        language = (result.language or "").lower()[:2]
        if self._indic is not None and language in INDIC_LANGUAGES:
            try:
                refined = await self._indic.transcribe(chunk)
                if not refined.is_empty:
                    # Keep the language Whisper detected: Sarvam reports the
                    # code it was asked to use, which is less informative.
                    return refined.model_copy(update={"language": result.language})
            except TranscriptionError as exc:
                logger.warning(
                    "Sarvam refinement failed for %s speech (%s); keeping Whisper output.",
                    language,
                    exc,
                )
        return result


class NullTranscriber:
    """Used when no STT credential is configured.

    Refuses rather than pretending. Live mode reports that audio capture
    is unavailable instead of producing an empty transcript that would
    look like a silent meeting.
    """

    name = "none"

    async def transcribe(self, chunk: AudioChunk) -> TranscriptionResult:
        raise TranscriptionError(
            "No speech-to-text engine is configured. Set GROQ_API_KEY (Whisper) "
            "or SARVAM_API_KEY to enable live audio capture."
        )


class ScriptedTranscriber:
    """Test double. Returns queued transcripts in order, per track.

    Lets the whole live path — websocket, attribution, extraction, gate —
    be tested end to end without a network call or an audio fixture.
    """

    name = "scripted"

    def __init__(self, script: Optional[dict[str, list[str]]] = None) -> None:
        self.script: dict[str, list[str]] = {k: list(v) for k, v in (script or {}).items()}
        self.received: list[AudioChunk] = []

    def queue(self, track: str, text: str) -> None:
        self.script.setdefault(track, []).append(text)

    async def transcribe(self, chunk: AudioChunk) -> TranscriptionResult:
        self.received.append(chunk)
        pending = self.script.get(chunk.track) or []
        if not pending:
            raise TranscriptionError(f"no scripted transcript left for track {chunk.track!r}")
        text = pending.pop(0)
        return TranscriptionResult(
            text=text,
            language="en",
            spans=[
                TranscriptSpan(
                    text=text,
                    start_ms=chunk.offset_ms,
                    end_ms=chunk.offset_ms + max(chunk.duration_ms, 1000),
                )
            ],
            engine=self.name,
        )


def build_transcriber(settings: Settings | None = None) -> Transcriber:
    """Assemble the configured transcription stack."""
    settings = settings or get_settings()

    primary: Optional[Transcriber] = None
    indic: Optional[Transcriber] = None

    if settings.groq_api_key:
        from app.adapters.transcription.groq_whisper import GroqWhisperTranscriber

        primary = GroqWhisperTranscriber(settings)
    if settings.sarvam_api_key:
        from app.adapters.transcription.sarvam import SarvamTranscriber

        indic = SarvamTranscriber(settings)

    if primary is None and indic is None:
        return NullTranscriber()
    if primary is None:
        return indic  # type: ignore[return-value]
    return AutoTranscriber(primary, indic, settings)
