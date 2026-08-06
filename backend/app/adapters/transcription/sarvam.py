"""Sarvam Saarika — Indian-language and code-mixed speech recognition.

Whisper handles English well and Indian languages passably. Saarika v2.5
is built for eleven Indian languages and, critically for a Bengaluru
standup, for *code-mixed* speech — the "Monday varaku share chesthava?"
case this product is built around.

Used as the second leg of the auto-router: Whisper transcribes first and
reports a detected language; if that language is Indic, the same chunk is
re-transcribed here. That costs a second call on Indic speech only, and
buys markedly better text on exactly the sentences the demo turns on.
"""
from __future__ import annotations

import httpx

from app.adapters.transcription.base import (
    AudioChunk,
    TranscriptionError,
    TranscriptionResult,
    TranscriptSpan,
)
from app.adapters.transcription.languages import normalize_language_code
from app.core.config import Settings, get_settings


class SarvamTranscriber:
    name = "sarvam_saarika"

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    async def transcribe(self, chunk: AudioChunk) -> TranscriptionResult:
        if not self._settings.sarvam_api_key:
            raise TranscriptionError("SARVAM_API_KEY is not set.")
        if not chunk.data:
            raise TranscriptionError("empty audio chunk")

        url = f"{self._settings.sarvam_api_base}/speech-to-text"
        headers = {"api-subscription-key": self._settings.sarvam_api_key}
        files = {"file": (chunk.filename, chunk.data, chunk.mime)}
        data = {
            "model": self._settings.sarvam_stt_model,
            # "unknown" asks Saarika to auto-detect, which is what makes
            # code-mixed input workable without pre-splitting by language.
            "language_code": normalize_language_code(self._settings.sarvam_language_code),
        }

        try:
            if self._client is not None:
                response = await self._client.post(url, headers=headers, files=files, data=data)
            else:
                async with httpx.AsyncClient(timeout=self._settings.groq_timeout_seconds) as client:
                    response = await client.post(url, headers=headers, files=files, data=data)
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"Sarvam transcription request failed: {exc}") from exc

        if response.status_code != 200:
            raise TranscriptionError(
                f"Sarvam transcription returned {response.status_code}: {response.text[:300]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TranscriptionError(f"Sarvam returned non-JSON: {exc}") from exc

        text = (payload.get("transcript") or "").strip()
        if not text:
            raise TranscriptionError("Sarvam returned no transcript")

        return TranscriptionResult(
            text=text,
            language=payload.get("language_code"),
            spans=[
                TranscriptSpan(
                    text=text,
                    start_ms=chunk.offset_ms,
                    end_ms=chunk.offset_ms + chunk.duration_ms,
                )
            ],
            engine=self.name,
        )
