"""Audio and video ingestion — turning a recording into transcript segments.

The upload path used to accept only ``.txt`` / ``.vtt`` / ``.srt``, which
meant the most obvious thing a user would try — dropping in the meeting
recording — failed with "must be UTF-8 text". This module closes that gap.

Three things have to happen, and each has a failure mode worth naming:

1. **Decode to something Whisper accepts.** Browsers and phones produce
   webm/opus, m4a, mp4, mov. ffmpeg normalizes all of it to 16 kHz mono
   WAV, which is also the smallest representation that loses no accuracy
   for speech.
2. **Split long recordings.** A 45-minute meeting exceeds the API's file
   limit, so audio is cut into overlapping-free windows on a fixed
   duration and each is transcribed separately. Offsets are tracked so
   the reassembled transcript keeps real timestamps.
3. **Refuse to invent speakers.** This is the important one.

## Why every segment says "Unknown speaker"

A raw recording carries no speaker labels. Whisper returns words, not
who said them. The honest representation of that is a single unattributed
speaker, and the consequence is deliberate: owner resolution fails closed,
so nothing extracted from an untagged recording can be auto-approved.

The alternative — guessing, or attributing everything to whoever uploaded
the file — would manufacture exactly the kind of false attribution the
safety gate exists to prevent. A reviewer tags speakers in the UI, and
tagging is what unlocks approval. Empty is better than wrong.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.adapters.transcription.base import AudioChunk, Transcriber, TranscriptionError
from app.services.ingestion.parser import RawUtterance, TranscriptParseError

logger = logging.getLogger("nexvi_meets.media")

#: Speech from a recording nobody has tagged yet. Matches the live path's
#: placeholder in spirit: present in the transcript, unable to own work.
UNKNOWN_SPEAKER = "Unknown speaker"

AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "ogg", "oga", "opus", "flac", "wma", "webm"}
VIDEO_EXTENSIONS = {"mp4", "mov", "mkv", "avi", "webm", "m4v", "wmv", "flv"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

#: Whisper on Groq rejects files over 100MB. 16 kHz mono WAV is about
#: 32 kB/s, so ~10 minutes stays comfortably inside that with room for
#: the container overhead.
CHUNK_SECONDS = 600
_WAV_BYTES_PER_SECOND = 16_000 * 2  # 16 kHz, 16-bit, mono


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def is_media(filename: str) -> bool:
    return extension_of(filename) in MEDIA_EXTENSIONS


def is_video(filename: str) -> bool:
    return extension_of(filename) in VIDEO_EXTENSIONS


class MediaIngestionError(TranscriptParseError):
    """Raised when a recording cannot be turned into a transcript.

    Subclasses ``TranscriptParseError`` so the upload route's existing
    error handling reports it as a 422 with the message intact.
    """


@dataclass
class MediaTranscript:
    """The result of transcribing one recording."""

    utterances: list[RawUtterance] = field(default_factory=list)
    duration_seconds: float = 0.0
    engine: str = "unknown"
    language: Optional[str] = None
    chunks: int = 0
    warnings: list[str] = field(default_factory=list)


def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def require_ffmpeg() -> str:
    path = ffmpeg_path()
    if path:
        return path
    raise MediaIngestionError(
        "ffmpeg is required to read audio and video, and is not installed. "
        "Install it with 'brew install ffmpeg' (macOS), "
        "'sudo apt install ffmpeg' (Linux), or upload a .txt/.vtt/.srt "
        "transcript instead."
    )


def probe_duration(path: Path) -> float:
    """Length in seconds, or 0.0 if ffprobe cannot tell.

    Used only to decide how many chunks to cut and to report progress, so
    an unknown duration degrades to "transcribe it in one go" rather than
    to a failure.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def extract_audio_chunks(
    source: Path, workdir: Path, chunk_seconds: int = CHUNK_SECONDS
) -> list[tuple[Path, int]]:
    """Decode to 16 kHz mono WAV, split into chunks.

    Returns ``(path, offset_ms)`` pairs in order. Video is handled by the
    same call — ``-vn`` simply discards the picture, so there is no
    separate code path to keep in sync.
    """
    ffmpeg = require_ffmpeg()
    pattern = workdir / "chunk_%04d.wav"

    command = [
        ffmpeg, "-nostdin", "-y",
        "-i", str(source),
        "-vn",                      # drop video; we only ever wanted sound
        "-ac", "1",                 # mono
        "-ar", "16000",             # 16 kHz is Whisper's native rate
        "-c:a", "pcm_s16le",
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-reset_timestamps", "1",
        str(pattern),
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        raise MediaIngestionError(
            "Decoding the recording took longer than 30 minutes and was stopped. "
            "Try trimming the file or converting it to audio first."
        ) from exc
    except OSError as exc:
        raise MediaIngestionError(f"Could not run ffmpeg: {exc}") from exc

    chunks = sorted(workdir.glob("chunk_*.wav"))
    if not chunks:
        # ffmpeg's last stderr lines say far more than its exit code.
        tail = "\n".join((result.stderr or "").strip().splitlines()[-4:])
        raise MediaIngestionError(
            "No audio could be read from this file. It may be a video with no "
            "audio track, or a format ffmpeg cannot decode."
            + (f"\n\nffmpeg said: {tail}" if tail else "")
        )

    return [(path, index * chunk_seconds * 1000) for index, path in enumerate(chunks)]


def _split_into_utterances(
    text: str, start_ms: int, duration_ms: int, speaker: str
) -> list[RawUtterance]:
    """Break a chunk's text into sentence-ish utterances.

    Whisper returns a wall of text per chunk. The extractor cites
    ``segment_id``s, so one giant segment would make every quote point at
    the whole meeting and make the evidence drawer useless. Splitting on
    sentence boundaries keeps citations precise.

    Timestamps are interpolated by character position. They are honest
    about being approximate — good enough to order the transcript and to
    show a rough time, not presented as exact.
    """
    import re

    pieces = [p.strip() for p in re.split(r"(?<=[.!?。？！])\s+", text) if p.strip()]
    if not pieces:
        return []

    total_chars = sum(len(p) for p in pieces) or 1
    utterances: list[RawUtterance] = []
    elapsed = 0

    for piece in pieces:
        share = len(piece) / total_chars
        span = int(duration_ms * share)
        utterances.append(
            RawUtterance(
                speaker=speaker,
                text=piece,
                start_ms=start_ms + elapsed,
                end_ms=start_ms + elapsed + span,
            )
        )
        elapsed += span

    return utterances


async def transcribe_media(
    *,
    data: bytes,
    filename: str,
    transcriber: Transcriber,
    speaker: str = UNKNOWN_SPEAKER,
    chunk_seconds: int = CHUNK_SECONDS,
) -> MediaTranscript:
    """Turn a recording into utterances.

    ``speaker`` defaults to ``UNKNOWN_SPEAKER``. Callers may pass a real
    name only when the user has asserted the recording is one person —
    never inferred from the file.
    """
    if not data:
        raise MediaIngestionError("The uploaded file is empty.")

    require_ffmpeg()
    result = MediaTranscript()

    with tempfile.TemporaryDirectory(prefix="nexvi-media-") as tmp:
        workdir = Path(tmp)
        source = workdir / f"source.{extension_of(filename) or 'bin'}"
        source.write_bytes(data)

        result.duration_seconds = probe_duration(source)
        chunks = extract_audio_chunks(source, workdir, chunk_seconds)
        result.chunks = len(chunks)

        for index, (chunk_path, offset_ms) in enumerate(chunks):
            audio = chunk_path.read_bytes()
            # A WAV header with no samples is silence, not speech.
            if len(audio) <= 44:
                continue

            duration_ms = int(
                (len(audio) - 44) / _WAV_BYTES_PER_SECOND * 1000
            ) or chunk_seconds * 1000

            try:
                transcription = await transcriber.transcribe(
                    AudioChunk(
                        track="mic",
                        seq=index,
                        data=audio,
                        mime="audio/wav",
                        offset_ms=offset_ms,
                        duration_ms=duration_ms,
                    )
                )
            except TranscriptionError as exc:
                # One bad chunk must not lose the rest of the meeting, but
                # it must not be silently skipped either.
                logger.warning("chunk %s of %s failed: %s", index + 1, len(chunks), exc)
                result.warnings.append(
                    f"Minute {offset_ms // 60000}–{(offset_ms + duration_ms) // 60000} "
                    f"could not be transcribed: {exc}"
                )
                continue

            if transcription.is_empty:
                continue

            result.engine = transcription.engine
            result.language = result.language or transcription.language
            result.utterances.extend(
                _split_into_utterances(
                    transcription.text, offset_ms, duration_ms, speaker
                )
            )

    if not result.utterances:
        raise MediaIngestionError(
            "No speech was found in this recording. If it definitely contains "
            "speech, check that the audio track is not silent and that a "
            "speech-to-text key (GROQ_API_KEY) is configured."
            + ("\n\n" + "\n".join(result.warnings) if result.warnings else "")
        )

    return result
