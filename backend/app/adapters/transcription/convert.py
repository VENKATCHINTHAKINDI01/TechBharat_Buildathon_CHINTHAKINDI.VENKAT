"""Audio format conversion for Sarvam compatibility.

Sarvam's speech-to-text endpoint only accepts:
  audio/mpeg, audio/mp3, audio/wav, audio/aac, audio/aiff, audio/pcm_s16le
  and a few aliases.

The browser's MediaRecorder produces audio/webm;codecs=opus — which Sarvam
rejects with a 400. This module converts webm/opus bytes to WAV (PCM 16-bit,
16kHz mono) using ffmpeg via subprocess before the bytes reach Sarvam.

ffmpeg is the only reliable cross-platform way to decode webm/opus without
pulling in a large native library. It handles all the codec quirks (Opus in
WebM container, variable bitrate, etc.) that pure-Python libraries struggle with.

If ffmpeg is not installed the raw bytes are returned unchanged and a warning
is logged so the operator knows exactly why Sarvam is rejecting the audio.
"""
from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("nexvi_meets.audio_convert")

# Sarvam accepts these MIME types (from their 400 error message)
SARVAM_SUPPORTED = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mpeg3",
    "audio/x-mpeg-3",
    "audio/x-mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/pcm_s16le",
    "audio/l16",
    "audio/raw",
    "application/octet-stream",
    "audio/aac",
    "audio/x-aac",
    "audio/aiff",
}


def needs_conversion(mime: str) -> bool:
    """Return True if this MIME type is not accepted by Sarvam."""
    # Strip codec parameters: "audio/webm;codecs=opus" -> "audio/webm"
    base = mime.split(";")[0].strip().lower()
    return base not in SARVAM_SUPPORTED


def _ffmpeg_path() -> str | None:
    """Find ffmpeg — prefer Homebrew path, fall back to PATH lookup."""
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "ffmpeg"):
        if shutil.which(candidate):
            return candidate
    return None


def convert_to_wav(audio_bytes: bytes, source_mime: str) -> tuple[bytes, str]:
    """Convert audio bytes to WAV (PCM 16-bit, 16kHz, mono).

    Returns (converted_bytes, new_mime). If conversion is not possible
    (ffmpeg missing, conversion fails), returns the original bytes and
    mime unchanged so the caller can still try — Sarvam may return a
    400, which is a clearer error than a silent local failure.
    """
    if not needs_conversion(source_mime):
        return audio_bytes, source_mime

    ffmpeg = _ffmpeg_path()
    if ffmpeg is None:
        logger.warning(
            "ffmpeg not found — cannot convert %s to WAV for Sarvam. "
            "Install ffmpeg: brew install ffmpeg",
            source_mime,
        )
        return audio_bytes, source_mime

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "input.webm"
            dst = Path(tmpdir) / "output.wav"
            src.write_bytes(audio_bytes)

            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",                   # overwrite output
                    "-i", str(src),         # input file
                    "-ar", "16000",         # 16kHz sample rate (Sarvam/Whisper standard)
                    "-ac", "1",             # mono
                    "-acodec", "pcm_s16le", # PCM 16-bit little-endian WAV
                    str(dst),
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "ffmpeg conversion failed (exit %d): %s",
                    result.returncode,
                    result.stderr.decode(errors="replace")[-300:],
                )
                return audio_bytes, source_mime

            wav_bytes = dst.read_bytes()
            logger.debug(
                "Converted %s (%d bytes) -> WAV (%d bytes)",
                source_mime, len(audio_bytes), len(wav_bytes),
            )
            return wav_bytes, "audio/wav"

    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg conversion timed out for %s", source_mime)
        return audio_bytes, source_mime
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffmpeg conversion raised %s: %s", type(exc).__name__, exc)
        return audio_bytes, source_mime
