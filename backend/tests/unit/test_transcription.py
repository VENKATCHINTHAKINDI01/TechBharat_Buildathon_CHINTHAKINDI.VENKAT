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


# --- language codes --------------------------------------------------------
#
# A wrong language_code was rejected by Sarvam with a 400 during the
# END-OF-MEETING diarization pass -- after the call was over and the audio
# already captured. These pin the coercion so a config typo cannot get
# that far again.


def test_auto_detect_spellings_all_mean_unknown():
    from app.adapters.transcription.languages import normalize_language_code

    for spelling in ["auto-detect", "auto", "autodetect", "auto_detect", "detect", "", "  ", None]:
        assert normalize_language_code(spelling) == "unknown", spelling


def test_valid_sarvam_codes_pass_through():
    from app.adapters.transcription.languages import SARVAM_LANGUAGE_CODES, normalize_language_code

    for code in SARVAM_LANGUAGE_CODES:
        assert normalize_language_code(code) == code


def test_bare_and_named_languages_expand_to_the_regional_form():
    from app.adapters.transcription.languages import normalize_language_code

    assert normalize_language_code("te") == "te-IN"
    assert normalize_language_code("Telugu") == "te-IN"
    assert normalize_language_code("hindi") == "hi-IN"
    assert normalize_language_code("TE-IN") == "te-IN"


def test_an_unrecognised_code_degrades_to_auto_detect():
    from app.adapters.transcription.languages import normalize_language_code

    assert normalize_language_code("klingon") == "unknown"


def test_settings_coerce_a_bad_language_code_at_startup():
    """Caught at load time, so the worst case is a log line rather than a
    400 at the end of a meeting."""
    assert Settings(sarvam_language_code="auto-detect").sarvam_language_code == "unknown"
    assert Settings(sarvam_language_code="Telugu").sarvam_language_code == "te-IN"


async def test_the_transcriber_never_sends_an_invalid_language_code():
    from app.adapters.transcription.languages import SARVAM_LANGUAGE_CODES

    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", "ignore")
        for code in SARVAM_LANGUAGE_CODES:
            if f'\r\n\r\n{code}\r\n' in body:
                sent["language_code"] = code
        return httpx.Response(200, json={"transcript": "hello", "language_code": "en-IN"})

    # Even if something bypasses the Settings validator, the call site coerces.
    settings = Settings(sarvam_api_key="k")
    object.__setattr__(settings, "sarvam_language_code", "auto-detect")

    await SarvamTranscriber(settings, client=_client(handler)).transcribe(_chunk())
    assert sent.get("language_code") == "unknown"


async def test_the_diarizer_never_sends_an_invalid_language_code():
    from app.adapters.transcription.languages import SARVAM_LANGUAGE_CODES
    from app.services.diarization import SarvamDiarizer

    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", "ignore")
        for code in SARVAM_LANGUAGE_CODES:
            if f'\r\n\r\n{code}\r\n' in body:
                sent["language_code"] = code
        return httpx.Response(200, json={"diarized_transcript": {"entries": []}})

    settings = Settings(sarvam_api_key="k")
    object.__setattr__(settings, "sarvam_language_code", "auto-detect")

    await SarvamDiarizer(settings, client=_client(handler)).diarize(b"audio", "audio/webm")
    assert sent.get("language_code") == "unknown"
