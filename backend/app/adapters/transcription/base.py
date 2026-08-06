"""Speech-to-text seam.

Live mode captures two audio tracks in the browser — the local microphone
(you) and the shared meeting-tab audio (everyone else) — and ships each as
a short, self-contained audio file. This module defines what a
transcriber receives and returns, so Whisper, Sarvam, or anything added
later are interchangeable and the live session never depends on one
vendor.

Why chunks rather than a stream: a browser's ``MediaRecorder`` produces
WebM where only the *first* blob carries the container header, so slicing
a single recording yields chunks nothing can decode. The frontend cycles
a fresh recorder per interval instead, making every chunk a complete
file. That also means any batch STT endpoint works — no streaming
protocol required — which is what lets Groq's Whisper (a file endpoint at
~216x realtime) drive a live experience.
"""
from __future__ import annotations

from typing import Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# "mic"    -> the local participant, attribution is certain
# "remote" -> the shared meeting tab: one or more other people, unknown which
TrackName = Literal["mic", "remote"]


class AudioChunk(BaseModel):
    """One self-contained audio file captured from a single track."""

    track: TrackName
    seq: int
    data: bytes
    mime: str = "audio/webm"
    # Milliseconds since the session started, so segments from the two
    # tracks can be interleaved into one honest timeline.
    offset_ms: int = 0
    duration_ms: int = 0

    model_config = {"arbitrary_types_allowed": True}

    @property
    def filename(self) -> str:
        ext = "webm"
        if "ogg" in self.mime:
            ext = "ogg"
        elif "mp4" in self.mime or "mp4a" in self.mime:
            ext = "mp4"
        elif "wav" in self.mime:
            ext = "wav"
        return f"{self.track}-{self.seq:05d}.{ext}"


class TranscriptSpan(BaseModel):
    """A timed piece of recognised speech within a chunk."""

    text: str
    start_ms: int = 0
    end_ms: int = 0
    # Set only when the provider itself separated speakers. Never invented.
    speaker_hint: Optional[str] = None


class TranscriptionResult(BaseModel):
    text: str
    language: Optional[str] = None
    spans: list[TranscriptSpan] = Field(default_factory=list)
    engine: str = "unknown"

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class TranscriptionError(RuntimeError):
    """A chunk could not be transcribed.

    Callers drop the chunk and carry on. Losing six seconds of audio is
    recoverable; inventing words to fill the gap is not, and would poison
    the evidence quotes the safety gate depends on.
    """


@runtime_checkable
class Transcriber(Protocol):
    name: str

    async def transcribe(self, chunk: AudioChunk) -> TranscriptionResult: ...


# Languages where Sarvam's Indian-language models beat general Whisper,
# and where code-mixing with English is common enough to matter.
INDIC_LANGUAGES = {
    "te",  # Telugu
    "hi",  # Hindi
    "ta",  # Tamil
    "kn",  # Kannada
    "ml",  # Malayalam
    "bn",  # Bengali
    "gu",  # Gujarati
    "mr",  # Marathi
    "pa",  # Punjabi
    "od",  # Odia
    "or",
}
