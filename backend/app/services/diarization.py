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

import asyncio
import time

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
        speaker = entry.get("speaker_id")
        if speaker is None:
            speaker = entry.get("speaker")
        if speaker is None:
            continue
        # Sarvam's batch API returns bare indices ("0", "1"); this module,
        # the mapping code and the UI all speak SPEAKER_00. Normalising
        # here keeps a raw "0" from surfacing as a cluster name in front
        # of a reviewer being asked "who is this?".
        speaker = str(speaker)
        if speaker.isdigit():
            speaker = f"SPEAKER_{int(speaker):02d}"
        start = entry.get("start_time_seconds", entry.get("start"))
        end = entry.get("end_time_seconds", entry.get("end"))
        if start is None or end is None:
            continue
        try:
            turns.append(
                SpeakerTurn(
                    speaker=speaker,
                    start_ms=int(float(start) * 1000),
                    end_ms=int(float(end) * 1000),
                )
            )
        except (TypeError, ValueError):
            continue
    return turns


class SarvamBatchDiarizer:
    """Speaker diarization via Sarvam's **batch** job API.

    The obvious call -- ``POST /speech-to-text`` with
    ``with_diarization=true`` -- returns HTTP 400: *"Diarization is not
    supported in the real-time API. Please use the batch API."* That is
    what this class exists to do properly.

    It is a five-step async workflow, not a request:

    1. initiate a job, getting a ``job_id``
    2. ask for a presigned upload URL
    3. PUT the audio to that URL
    4. start the job
    5. poll until it completes, then download the result JSON

    **Polling is time-boxed.** Diarization runs when a meeting ends,
    which is exactly when someone is waiting to see the report. A job
    that has not finished inside the budget is abandoned and the meeting
    proceeds with manual speaker tagging -- degraded, but never a demo
    hanging on a spinner. `wait_until_complete` in Sarvam's own SDK
    defaults to a ten-minute timeout, which would be unusable here.
    """

    name = "sarvam_batch"

    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {"api-subscription-key": self._settings.sarvam_api_key}

    async def _json(self, client, method: str, url: str, step: str, **kwargs) -> dict:
        response = await client.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code >= 400:
            raise DiarizationError(
                f"Sarvam batch diarization failed at '{step}': "
                f"HTTP {response.status_code} — {response.text[:280]}"
            )
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise DiarizationError(f"Sarvam returned non-JSON at '{step}': {exc}") from exc

    async def diarize(self, audio: bytes, mime: str) -> DiarizationResult:
        settings = self._settings
        if not settings.sarvam_api_key:
            raise DiarizationError("SARVAM_API_KEY is not set.")
        if not audio:
            return DiarizationResult(engine=self.name, error="no audio buffered")

        audio_bytes, audio_mime = convert_to_wav(audio, mime)
        filename = "remote-track.wav" if audio_mime != mime else "remote-track.webm"
        base = f"{settings.sarvam_api_base}/speech-to-text/job/v1"
        deadline = time.monotonic() + settings.sarvam_diarization_timeout_seconds

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=60.0)
        try:
            # 1. initiate
            job = await self._json(
                client, "POST", base, "initiate",
                json={
                    "job_parameters": {
                        "model": settings.sarvam_batch_model,
                        "language_code": normalize_language_code(settings.sarvam_language_code),
                        "with_diarization": True,
                        "with_timestamps": True,
                        "num_speakers": settings.sarvam_max_speakers,
                    }
                },
            )
            job_id = job.get("job_id")
            if not job_id:
                raise DiarizationError(f"Sarvam did not return a job id: {job}")

            # 2. presigned upload URL
            upload = await self._json(
                client, "POST", f"{base}/upload-files", "upload-files",
                json={"job_id": job_id, "files": [filename]},
            )
            urls = upload.get("upload_urls") or {}
            target = (urls.get(filename) or next(iter(urls.values()), {})).get("file_url")
            if not target:
                raise DiarizationError(f"Sarvam returned no upload URL: {upload}")

            # 3. PUT the bytes. Azure blob storage rejects a plain PUT
            # without this header, and the container type says Azure.
            put_headers = {"Content-Type": audio_mime}
            if str(upload.get("storage_container_type", "")).lower().startswith("azure"):
                put_headers["x-ms-blob-type"] = "BlockBlob"
            put = await client.put(target, content=audio_bytes, headers=put_headers)
            if put.status_code >= 400:
                raise DiarizationError(
                    f"Uploading audio to Sarvam storage failed: HTTP {put.status_code}"
                )

            # 4. start
            await self._json(client, "POST", f"{base}/{job_id}/start", "start")

            # 5. poll, within budget
            outputs: list[str] = []
            while True:
                if time.monotonic() > deadline:
                    raise DiarizationError(
                        f"Sarvam diarization did not finish within "
                        f"{settings.sarvam_diarization_timeout_seconds:.0f}s. The meeting is "
                        "saved; tag speakers by hand, or raise "
                        "SARVAM_DIARIZATION_TIMEOUT_SECONDS."
                    )
                status = await self._json(
                    client, "GET", f"{base}/{job_id}/status", "status"
                )
                state = str(status.get("job_state", ""))
                if state == "Completed":
                    for detail in status.get("job_details") or []:
                        outputs += [o["file_name"] for o in detail.get("outputs") or []]
                    break
                if state == "Failed":
                    raise DiarizationError(
                        f"Sarvam job failed: {status.get('error_message') or 'no reason given'}"
                    )
                await asyncio.sleep(settings.sarvam_diarization_poll_seconds)

            if not outputs:
                return DiarizationResult(engine=self.name, error="job produced no output files")

            # 6. download the result
            download = await self._json(
                client, "POST", f"{base}/download-files", "download-files",
                json={"job_id": job_id, "files": outputs[:1]},
            )
            links = download.get("download_urls") or download.get("upload_urls") or {}
            link = (links.get(outputs[0]) or next(iter(links.values()), {})).get("file_url")
            if not link:
                raise DiarizationError(f"Sarvam returned no download URL: {download}")

            fetched = await client.get(link)
            if fetched.status_code >= 400:
                raise DiarizationError(f"Could not fetch the result: HTTP {fetched.status_code}")

            return DiarizationResult(turns=parse_sarvam_turns(fetched.json()), engine=self.name)
        except httpx.HTTPError as exc:
            raise DiarizationError(f"Sarvam batch request failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()


def build_diarizer(settings: Settings | None = None) -> Diarizer:
    settings = settings or get_settings()
    if settings.sarvam_api_key and settings.live_diarization_enabled:
        # The batch API is the only one that does diarization at all.
        return SarvamBatchDiarizer(settings)
    return NullDiarizer()
