/**
 * Browser audio capture for live meeting mode.
 *
 * Two tracks:
 *   mic    — getUserMedia, the local participant, attribution is certain
 *   remote — getDisplayMedia with audio, i.e. the shared Meet/Zoom tab
 *
 * The important detail: a MediaRecorder emits WebM where only the FIRST
 * blob carries the container header. Slicing one long recording with
 * `start(timeslice)` therefore produces chunks that nothing can decode
 * after the first. So instead of slicing, this cycles a fresh recorder
 * per interval — every chunk is a complete, independently decodable file,
 * which is also what lets a plain file-upload STT endpoint (Groq Whisper)
 * drive a live experience with no streaming protocol.
 */

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

export function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) || "audio/webm";
}

/**
 * Tab-audio capture is a Chromium feature. Firefox has no equivalent and
 * Safari's support is too limited to rely on, so detect up front rather
 * than letting someone discover it mid-demo.
 */
export function tabAudioSupport() {
  if (typeof navigator === "undefined") return { supported: false, browser: "unknown" };
  const ua = navigator.userAgent;
  const isEdge = /Edg\//.test(ua);
  const isChrome = /Chrome\//.test(ua) && !/OPR\//.test(ua);
  const isFirefox = /Firefox\//.test(ua);
  const isSafari = /Safari\//.test(ua) && !/Chrome\//.test(ua);

  if (isEdge) return { supported: true, browser: "Edge" };
  if (isChrome) return { supported: true, browser: "Chrome" };
  if (isFirefox)
    return {
      supported: false,
      browser: "Firefox",
      reason: "Firefox cannot capture tab audio. Use Chrome or Edge to hear the other participants.",
    };
  if (isSafari)
    return {
      supported: false,
      browser: "Safari",
      reason: "Safari's tab-audio support is too limited to rely on. Use Chrome or Edge.",
    };
  return { supported: Boolean(navigator.mediaDevices?.getDisplayMedia), browser: "this browser" };
}

export function isCaptureSupported() {
  return Boolean(
    typeof navigator !== "undefined" &&
      navigator.mediaDevices?.getUserMedia &&
      typeof MediaRecorder !== "undefined"
  );
}

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  // Chunked to avoid blowing the argument limit on large buffers.
  const STEP = 0x8000;
  for (let i = 0; i < bytes.length; i += STEP) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + STEP));
  }
  return btoa(binary);
}

/**
 * Records one track as a sequence of complete audio files.
 * Calls `onChunk({ track, seq, data, mime, offset_ms, duration_ms })`.
 */
export class TrackRecorder {
  constructor(stream, track, onChunk, chunkSeconds = 6) {
    this.stream = stream;
    this.track = track;
    this.onChunk = onChunk;
    this.chunkMs = chunkSeconds * 1000;
    this.mime = pickMimeType();
    this.seq = 0;
    this.startedAt = 0;
    this.running = false;
    this._recorder = null;
    this._timer = null;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.startedAt = Date.now();
    this._cycle();
  }

  _cycle() {
    if (!this.running) return;

    let recorder;
    try {
      recorder = new MediaRecorder(this.stream, { mimeType: this.mime });
    } catch {
      recorder = new MediaRecorder(this.stream);
    }
    this._recorder = recorder;

    const offsetMs = Date.now() - this.startedAt;
    const parts = [];

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) parts.push(event.data);
    };

    recorder.onstop = async () => {
      if (parts.length) {
        const blob = new Blob(parts, { type: this.mime });
        // Sub-kilobyte blobs are silence or a truncated header; sending
        // them just burns an API call and risks a hallucinated word.
        if (blob.size > 1024) {
          try {
            this.onChunk({
              track: this.track,
              seq: this.seq++,
              data: await blobToBase64(blob),
              mime: this.mime,
              offset_ms: offsetMs,
              duration_ms: this.chunkMs,
            });
          } catch (err) {
            console.warn("[audioCapture] could not encode chunk", err);
          }
        }
      }
      // Immediately begin the next chunk.
      this._cycle();
    };

    recorder.start();
    this._timer = setTimeout(() => {
      if (recorder.state !== "inactive") recorder.stop();
    }, this.chunkMs);
  }

  stop() {
    this.running = false;
    clearTimeout(this._timer);
    if (this._recorder && this._recorder.state !== "inactive") {
      // onstop still fires, flushing the final partial chunk.
      this._recorder.onstop = async () => {};
      this._recorder.stop();
    }
    this.stream.getTracks().forEach((t) => t.stop());
  }
}

/** Microphone. Throws a human-readable error if permission is refused. */
export async function captureMicrophone() {
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (err) {
    throw new Error(
      `Microphone access was refused (${err.name}). Allow the mic for this site and try again.`
    );
  }
}

/**
 * The meeting tab's audio.
 *
 * Browsers only expose tab audio through the screen-share picker, and
 * only if the user ticks "Also share tab audio" — there is no way to
 * grab it silently, by design. The video track is stopped immediately;
 * we only ever wanted the sound.
 */
export async function captureTabAudio() {
  const support = tabAudioSupport();
  if (!support.supported) {
    throw new Error(support.reason || "This browser cannot capture tab audio. Use Chrome or Edge.");
  }

  let display;
  try {
    display = await navigator.mediaDevices.getDisplayMedia({
      video: true, // required: Chrome refuses audio-only display capture
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
  } catch (err) {
    throw new Error(
      `Tab audio capture was cancelled (${err.name}). Choose the "Chrome Tab" option — ` +
        'not "Entire Screen" — pick your meeting tab, and tick "Also share tab audio".'
    );
  }

  const audioTracks = display.getAudioTracks();
  if (audioTracks.length === 0) {
    display.getTracks().forEach((t) => t.stop());
    throw new Error(
      'No audio came through. The "Also share tab audio" tickbox only appears when you pick ' +
        'the "Chrome Tab" option — it is NOT offered for "Entire Screen" or "Window". ' +
        "Re-share, choose the tab with your meeting, and tick it before clicking Share. " +
        "Without it the browser sends video only and nobody else will be heard."
    );
  }

  // Drop the video; we never wanted the pixels.
  display.getVideoTracks().forEach((t) => {
    t.stop();
    display.removeTrack(t);
  });

  return new MediaStream(audioTracks);
}
