"""Sarvam batch diarization.

Every live meeting was ending with a red warning:

    Sarvam diarization returned 400: "Diarization is not supported in the
    real-time API. Please use the batch API for diarization."

The adapter was calling `POST /speech-to-text` with `with_diarization`,
which is the realtime endpoint and does not support it. Diarization is a
five-step asynchronous *job*: initiate, get a presigned URL, upload,
start, poll, download.

The behaviour these tests care about most is the **time box**. Diarization
runs when a meeting ends, which is precisely when someone is waiting to
see the report. Sarvam's own SDK helper defaults to a ten-minute timeout;
here, a job that overruns must be abandoned so the meeting still produces
a report, with manual speaker tagging as the honest fallback.
"""
import httpx
import pytest

from app.core.config import Settings
from app.services.diarization import (
    DiarizationError,
    NullDiarizer,
    SarvamBatchDiarizer,
    build_diarizer,
)

AUDIO = b"RIFF" + b"\x00" * 2000

DIARIZED = {
    "transcript": "Hello. I have a question.",
    "diarized_transcript": {
        "entries": [
            {"transcript": "Hello.", "start_time_seconds": 0.0,
             "end_time_seconds": 2.5, "speaker_id": "0"},
            {"transcript": "I have a question.", "start_time_seconds": 2.8,
             "end_time_seconds": 4.2, "speaker_id": "1"},
        ]
    },
}


def _settings(**overrides) -> Settings:
    return Settings(
        sarvam_api_key="test-key",
        live_diarization_enabled=True,
        sarvam_diarization_poll_seconds=0.0,  # no real sleeping in tests
        **overrides,
    )


class FakeSarvam:
    """A scripted Sarvam batch API.

    Records every call so the test can assert on the *shape* of the
    conversation, not just the final answer.
    """

    def __init__(self, *, states=("Completed",), fail_at=None, status_code=500):
        self.calls = []
        self.uploaded = None
        self.put_headers = {}
        self._states = list(states)
        self._fail_at = fail_at
        self._status_code = status_code

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        def maybe_fail(step):
            if self._fail_at == step:
                return httpx.Response(self._status_code, text='{"error":{"message":"nope"}}')
            return None

        if request.method == "POST" and path == "/speech-to-text/job/v1":
            return maybe_fail("initiate") or httpx.Response(
                202, json={"job_id": "job-1", "job_state": "Accepted",
                           "storage_container_type": "Azure_V1", "job_parameters": {}}
            )

        if path.endswith("/upload-files"):
            return maybe_fail("upload") or httpx.Response(
                200,
                json={
                    "job_id": "job-1", "job_state": "Accepted",
                    "storage_container_type": "Azure_V1",
                    "upload_urls": {
                        "remote-track.wav": {"file_url": "https://blob.example/upload"}
                    },
                },
            )

        if request.method == "PUT":
            self.uploaded = request.content
            self.put_headers = dict(request.headers)
            return maybe_fail("put") or httpx.Response(201)

        if path.endswith("/start"):
            return maybe_fail("start") or httpx.Response(200, json={"job_state": "Running"})

        if path.endswith("/status"):
            state = self._states.pop(0) if len(self._states) > 1 else self._states[0]
            body = {"job_id": "job-1", "job_state": state,
                    "created_at": "", "updated_at": "", "storage_container_type": "Azure_V1"}
            if state == "Completed":
                body["job_details"] = [{"outputs": [{"file_name": "0.json", "file_id": "o0"}]}]
            if state == "Failed":
                body["error_message"] = "the model exploded"
            return httpx.Response(200, json=body)

        if path.endswith("/download-files"):
            return maybe_fail("download") or httpx.Response(
                200,
                json={"download_urls": {"0.json": {"file_url": "https://blob.example/0.json"}}},
            )

        if str(request.url) == "https://blob.example/0.json":
            return httpx.Response(200, json=DIARIZED)

        return httpx.Response(404, text=f"unexpected {request.method} {path}")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


# --- the happy path -------------------------------------------------------


async def test_the_full_job_workflow_produces_speaker_turns():
    fake = FakeSarvam()
    result = await SarvamBatchDiarizer(_settings(), fake.client()).diarize(AUDIO, "audio/wav")

    assert result.engine == "sarvam_batch"
    assert [turn.speaker for turn in result.turns] == ["SPEAKER_00", "SPEAKER_01"]
    assert result.turns[0].start_ms == 0
    assert result.turns[1].end_ms == 4200


async def test_it_walks_the_five_steps_in_order():
    """If any step is skipped the job silently never runs, so the order
    is worth asserting rather than trusting."""
    fake = FakeSarvam()
    await SarvamBatchDiarizer(_settings(), fake.client()).diarize(AUDIO, "audio/wav")

    steps = [f"{method} {path}" for method, path in fake.calls]
    assert steps[0] == "POST /speech-to-text/job/v1"
    assert "POST /speech-to-text/job/v1/upload-files" in steps[1]
    assert steps[2].startswith("PUT")
    assert steps[3].endswith("/start")
    assert any(s.endswith("/status") for s in steps)
    assert any(s.endswith("/download-files") for s in steps)


async def test_the_audio_actually_reaches_the_presigned_url():
    fake = FakeSarvam()
    await SarvamBatchDiarizer(_settings(), fake.client()).diarize(AUDIO, "audio/wav")

    assert fake.uploaded, "the audio was never uploaded"
    # Azure blob storage rejects a plain PUT without this header, and the
    # container type in the response says Azure.
    assert fake.put_headers.get("x-ms-blob-type") == "BlockBlob"


async def test_it_waits_through_the_pending_states():
    fake = FakeSarvam(states=("Accepted", "Running", "Running", "Completed"))
    result = await SarvamBatchDiarizer(_settings(), fake.client()).diarize(AUDIO, "audio/wav")

    assert len(result.turns) == 2
    assert sum(1 for _, path in fake.calls if path.endswith("/status")) == 4


# --- the failures that matter ---------------------------------------------


async def test_polling_is_time_boxed_so_a_meeting_never_hangs():
    """The whole reason this is not just SDK.wait_until_complete()."""
    fake = FakeSarvam(states=("Running",))  # never finishes
    diarizer = SarvamBatchDiarizer(
        _settings(sarvam_diarization_timeout_seconds=0.05), fake.client()
    )

    with pytest.raises(DiarizationError, match="did not finish within"):
        await diarizer.diarize(AUDIO, "audio/wav")


async def test_a_failed_job_reports_the_reason_sarvam_gave():
    fake = FakeSarvam(states=("Failed",))
    with pytest.raises(DiarizationError, match="the model exploded"):
        await SarvamBatchDiarizer(_settings(), fake.client()).diarize(AUDIO, "audio/wav")


@pytest.mark.parametrize("step", ["initiate", "upload", "start", "download"])
async def test_every_step_names_itself_when_it_fails(step):
    """A bare 'Sarvam returned 400' sent someone hunting last time."""
    fake = FakeSarvam(fail_at=step, status_code=400)
    with pytest.raises(DiarizationError, match=step):
        await SarvamBatchDiarizer(_settings(), fake.client()).diarize(AUDIO, "audio/wav")


async def test_no_audio_is_reported_rather_than_uploaded():
    fake = FakeSarvam()
    result = await SarvamBatchDiarizer(_settings(), fake.client()).diarize(b"", "audio/wav")

    assert result.turns == []
    assert "no audio" in result.error
    assert fake.calls == [], "an empty job should never have been created"


async def test_a_missing_key_fails_before_any_request():
    fake = FakeSarvam()
    diarizer = SarvamBatchDiarizer(Settings(sarvam_api_key=""), fake.client())

    with pytest.raises(DiarizationError, match="SARVAM_API_KEY"):
        await diarizer.diarize(AUDIO, "audio/wav")
    assert fake.calls == []


# --- configuration --------------------------------------------------------


def test_the_batch_model_is_used_not_the_legacy_realtime_one():
    """`saarika` is legacy and the batch API rejects it outright. Getting
    this wrong is half of why the old call failed."""
    settings = _settings()
    assert settings.sarvam_batch_model.startswith("saaras")
    assert "saarika" not in settings.sarvam_batch_model


async def test_the_configured_batch_model_is_what_gets_sent():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/speech-to-text/job/v1":
            import json

            sent.update(json.loads(request.content)["job_parameters"])
        return FakeSarvam().handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await SarvamBatchDiarizer(_settings(), client).diarize(AUDIO, "audio/wav")

    assert sent["model"] == "saaras:v3"
    assert sent["with_diarization"] is True


def test_diarization_is_skipped_entirely_when_turned_off():
    assert isinstance(build_diarizer(Settings(sarvam_api_key="")), NullDiarizer)
    assert isinstance(
        build_diarizer(Settings(sarvam_api_key="k", live_diarization_enabled=False)),
        NullDiarizer,
    )


def test_the_batch_diarizer_is_the_one_that_gets_built():
    diarizer = build_diarizer(_settings())
    assert isinstance(diarizer, SarvamBatchDiarizer)
    assert diarizer.name == "sarvam_batch"
