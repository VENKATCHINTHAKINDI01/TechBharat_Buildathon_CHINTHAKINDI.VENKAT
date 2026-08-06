"""Transcription adapters and the language router. No network calls."""
import httpx
import pytest

from app.adapters.transcription.auto import AutoTranscriber, NullTranscriber
from app.adapters.transcription.base import (
    AudioChunk,
    TranscriptionError,
    TranscriptionResult,
    TranscriptSpan,
)
from app.adapters.transcription.groq_whisper import GroqWhisperTranscriber
from app.adapters.transcription.sarvam import SarvamTranscriber
from app.core.config import Settings


def _chunk(track="mic", offset_ms=0) -> AudioChunk:
    return AudioChunk(track=track, seq=0, data=b"audio", offset_ms=offset_ms, duration_ms=6000)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- chunk shape -----------------------------------------------------------


def test_filename_reflects_the_container():
    assert AudioChunk(track="mic", seq=3, data=b"x").filename == "mic-00003.webm"
    assert AudioChunk(track="remote", seq=1, data=b"x", mime="audio/mp4").filename.endswith(".mp4")


# --- Groq Whisper ----------------------------------------------------------


async def test_whisper_parses_segments_and_offsets_them():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "text": "I will finish it by Friday.",
                "language": "english",
                "segments": [{"start": 0.5, "end": 2.5, "text": " I will finish it by Friday."}],
            },
        )

    result = await GroqWhisperTranscriber(
        Settings(groq_api_key="k"), client=_client(handler)
    ).transcribe(_chunk(offset_ms=12000))

    assert result.text == "I will finish it by Friday."
    assert result.engine == "groq_whisper"
    # Span timings are absolute within the meeting, not within the chunk.
    assert result.spans[0].start_ms == 12500
    assert result.spans[0].end_ms == 14500


async def test_whisper_synthesises_a_span_when_none_are_returned():
    def handler(request):
        return httpx.Response(200, json={"text": "hello", "language": "english"})

    result = await GroqWhisperTranscriber(
        Settings(groq_api_key="k"), client=_client(handler)
    ).transcribe(_chunk())
    assert len(result.spans) == 1
    assert result.spans[0].text == "hello"


async def test_whisper_without_a_key_refuses():
    with pytest.raises(TranscriptionError, match="GROQ_API_KEY"):
        await GroqWhisperTranscriber(Settings(groq_api_key="")).transcribe(_chunk())


async def test_whisper_http_error_becomes_a_transcription_error():
    def handler(request):
        return httpx.Response(429, text="slow down")

    with pytest.raises(TranscriptionError, match="429"):
        await GroqWhisperTranscriber(
            Settings(groq_api_key="k"), client=_client(handler)
        ).transcribe(_chunk())


async def test_empty_chunk_is_refused():
    with pytest.raises(TranscriptionError, match="empty audio"):
        await GroqWhisperTranscriber(Settings(groq_api_key="k")).transcribe(
            AudioChunk(track="mic", seq=0, data=b"")
        )


# --- Sarvam ----------------------------------------------------------------


async def test_sarvam_parses_a_transcript():
    def handler(request):
        return httpx.Response(200, json={"transcript": "Monday ki pampistanu", "language_code": "te-IN"})

    result = await SarvamTranscriber(
        Settings(sarvam_api_key="k"), client=_client(handler)
    ).transcribe(_chunk())
    assert result.text == "Monday ki pampistanu"
    assert result.engine == "sarvam_saarika"


async def test_sarvam_empty_transcript_is_an_error_not_silence():
    def handler(request):
        return httpx.Response(200, json={"transcript": "  "})

    with pytest.raises(TranscriptionError, match="no transcript"):
        await SarvamTranscriber(
            Settings(sarvam_api_key="k"), client=_client(handler)
        ).transcribe(_chunk())


# --- the router ------------------------------------------------------------


class Fake:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self._result = result
        self._error = error
        self.calls = 0

    async def transcribe(self, chunk):
        self.calls += 1
        if self._error:
            raise TranscriptionError(self._error)
        return self._result


def _result(text, language, engine):
    return TranscriptionResult(
        text=text, language=language, engine=engine, spans=[TranscriptSpan(text=text)]
    )


async def test_english_stays_with_whisper():
    primary = Fake("whisper", _result("finish by Friday", "english", "whisper"))
    indic = Fake("sarvam", _result("should not be used", "te", "sarvam"))

    result = await AutoTranscriber(primary, indic).transcribe(_chunk())
    assert result.engine == "whisper"
    assert indic.calls == 0


async def test_indic_speech_is_refined_by_sarvam():
    primary = Fake("whisper", _result("monday key pampista", "te", "whisper"))
    indic = Fake("sarvam", _result("Monday ki పంపిస్తాను", "te-IN", "sarvam"))

    result = await AutoTranscriber(primary, indic).transcribe(_chunk())
    assert result.engine == "sarvam"
    assert result.text == "Monday ki పంపిస్తాను"
    # The detected language from Whisper is preserved; it is more informative.
    assert result.language == "te"


async def test_a_failed_refinement_keeps_the_whisper_output():
    primary = Fake("whisper", _result("monday key pampista", "hi", "whisper"))
    indic = Fake("sarvam", error="sarvam down")

    result = await AutoTranscriber(primary, indic).transcribe(_chunk())
    assert result.engine == "whisper"


async def test_a_failed_primary_falls_back_to_sarvam():
    primary = Fake("whisper", error="groq down")
    indic = Fake("sarvam", _result("recovered", "hi", "sarvam"))

    result = await AutoTranscriber(primary, indic).transcribe(_chunk())
    assert result.engine == "sarvam"


async def test_both_failing_raises_rather_than_inventing():
    primary = Fake("whisper", error="groq down")
    indic = Fake("sarvam", error="sarvam down")
    with pytest.raises(TranscriptionError):
        await AutoTranscriber(primary, indic).transcribe(_chunk())


async def test_null_transcriber_refuses_with_actionable_advice():
    with pytest.raises(TranscriptionError, match="GROQ_API_KEY"):
        await NullTranscriber().transcribe(_chunk())
