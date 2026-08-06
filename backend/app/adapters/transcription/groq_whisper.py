"""Groq-hosted Whisper Large v3 Turbo.

Endpoint: ``POST https://api.groq.com/openai/v1/audio/transcriptions``
(OpenAI-compatible multipart). Groq runs this at roughly 216x realtime,
which is what makes a *file* endpoint feel live: a six-second chunk comes
back in well under a second.

Uses ``verbose_json`` so we get per-segment timings and the detected
language. The language matters twice: it feeds the auto-router's decision
to re-transcribe Indic speech with Sarvam, and it is recorded in the
audit trail.
"""
from __future__ import annotations

import httpx

from app.adapters.transcription.base import (
    AudioChunk,
    TranscriptionError,
    TranscriptionResult,
    TranscriptSpan,
)
from app.core.config import Settings, get_settings


class GroqWhisperTranscriber:
    name = "groq_whisper"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def transcribe(self, chunk: AudioChunk) -> TranscriptionResult:
        if not self._settings.groq_api_key:
            raise TranscriptionError("GROQ_API_KEY is not set; cannot transcribe audio.")
        if not chunk.data:
            raise TranscriptionError("empty audio chunk")

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._settings.groq_api_key}"}
        files = {"file": (chunk.filename, chunk.data, chunk.mime)}
        data = {
            "model": self._settings.groq_transcription_model,
            "response_format": "verbose_json",
            # Nudges the model toward the vocabulary of a standup rather
            # than generic prose. Not a jailbreak surface: Whisper cannot
            # take actions, and the output is treated purely as text.
            "prompt": "Software team meeting. Names, deadlines, and commitments.",
        }
        if self._settings.live_asr_language:
            data["language"] = self._settings.live_asr_language

        try:
            if self._client is not None:
                response = await self._client.post(url, headers=headers, files=files, data=data)
            else:
                async with httpx.AsyncClient(timeout=self._settings.groq_timeout_seconds) as client:
                    response = await client.post(url, headers=headers, files=files, data=data)
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"Groq transcription request failed: {exc}") from exc

        if response.status_code != 200:
            raise TranscriptionError(
                f"Groq transcription returned {response.status_code}: {response.text[:300]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TranscriptionError(f"Groq returned non-JSON: {exc}") from exc

        return self._parse(payload, chunk)

    def _parse(self, payload: dict, chunk: AudioChunk) -> TranscriptionResult:
        text = (payload.get("text") or "").strip()
        spans: list[TranscriptSpan] = []
        for raw in payload.get("segments") or []:
            span_text = (raw.get("text") or "").strip()
            if not span_text:
                continue
            spans.append(
                TranscriptSpan(
                    text=span_text,
                    start_ms=chunk.offset_ms + int(float(raw.get("start", 0.0)) * 1000),
                    end_ms=chunk.offset_ms + int(float(raw.get("end", 0.0)) * 1000),
                )
            )

        if not spans and text:
            spans = [
                TranscriptSpan(
                    text=text,
                    start_ms=chunk.offset_ms,
                    end_ms=chunk.offset_ms + chunk.duration_ms,
                )
            ]

        return TranscriptionResult(
            text=text, language=payload.get("language"), spans=spans, engine=self.name
        )
