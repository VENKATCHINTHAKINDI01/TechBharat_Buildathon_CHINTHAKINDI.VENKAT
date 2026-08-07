/**
 * Reading participant names off the shared meeting screen.
 *
 * Meet, Zoom and Teams all draw the speaker's name as a small text
 * overlay on each video tile. That is the only reliable machine-readable
 * source of who is actually in the room — the audio certainly does not
 * carry it — so Naina reads it with OCR.
 *
 * ## Everything happens on this machine
 *
 * Tesseract runs in the browser via WebAssembly. **No frame is uploaded
 * anywhere.** That is not an implementation detail, it is the reason
 * this design was chosen: OCR'ing a shared tab means processing whatever
 * happens to be on that screen — a private chat, an email notification,
 * someone else's document. Sending those pixels to a third party to
 * learn four names would be a wildly disproportionate trade.
 *
 * ## Everything it finds is a proposal
 *
 * A name read off a video tile is a guess in a confident font. OCR
 * mangles characters, video-call display names are often not people
 * ("iPhone", "Conference Room 2", "Ravi's MacBook"), and a misread name
 * that silently became a participant would be an owner the safety gate
 * happily approves. So this module never adds anyone. It returns
 * candidates with confidence, and a human accepts them.
 */
import { createWorker } from "tesseract.js";

/** Tesseract is ~2MB of wasm; only fetch it if the feature is used. */
let workerPromise = null;

async function getWorker() {
  if (!workerPromise) {
    workerPromise = createWorker("eng");
  }
  return workerPromise;
}

export async function terminateWorker() {
  if (!workerPromise) return;
  try {
    const worker = await workerPromise;
    await worker.terminate();
  } catch {
    /* already gone */
  }
  workerPromise = null;
}

/**
 * Interface furniture that OCR reliably picks up and that is never a
 * person. Matched case-insensitively against the whole candidate.
 */
const UI_NOISE = new Set([
  "you", "me", "host", "co-host", "cohost", "guest", "guests", "presenting",
  "presentation", "screen", "sharing", "share", "shared screen", "screen share",
  "muted", "unmuted", "mute", "unmute", "camera", "mic", "microphone", "chat",
  "people", "participants", "details", "activities", "more", "options",
  "leave", "leave call", "end call", "join", "joining", "reconnecting",
  "recording", "meeting", "meet", "zoom", "teams", "raise hand", "reactions",
  "view", "grid", "speaker", "spotlight", "pinned", "pin", "settings",
  "captions", "turn on captions", "present now", "info", "waiting",
  "connecting", "poor connection", "unstable", "on", "off", "live",
]);

/** Substrings that give away a device rather than a person. */
const DEVICE_HINTS = [
  "iphone", "ipad", "android", "macbook", "galaxy", "pixel", "laptop",
  "desktop", "conference room", "meeting room", "room ", "tv", "device",
  "'s ", "’s ",
];

const NAME_SHAPE = /^[\p{L}][\p{L}'’.-]*(?:\s+[\p{L}][\p{L}'’.-]*){0,3}$/u;

/**
 * Is this OCR line plausibly a person's name?
 *
 * Deliberately strict. A false positive costs a human a moment of
 * confusion and, if they are not paying attention, a wrong owner. A
 * false negative costs one manual typing of a name. The asymmetry says
 * be strict.
 */
export function looksLikeName(raw) {
  const text = (raw || "").trim().replace(/\s+/g, " ");

  if (text.length < 2 || text.length > 40) return false;
  if (UI_NOISE.has(text.toLowerCase())) return false;
  if (DEVICE_HINTS.some((hint) => text.toLowerCase().includes(hint))) return false;

  // Names do not contain digits, and OCR loves inventing punctuation.
  if (/\d/.test(text)) return false;
  if (!NAME_SHAPE.test(text)) return false;

  // A single word in all-caps is far more often a label than a name.
  if (!text.includes(" ") && text === text.toUpperCase() && text.length > 3) return false;

  return true;
}

/** "  rohit   SHARMA " -> "Rohit Sharma" */
export function tidyName(raw) {
  return (raw || "")
    .trim()
    .replace(/\s+/g, " ")
    .split(" ")
    .map((word) =>
      word.length <= 1
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
    )
    .join(" ");
}

function normalise(name) {
  return tidyName(name).toLowerCase();
}

/**
 * OCR a frame and return proposed participant names.
 *
 * `known` is the names already in the meeting; anything matching one is
 * dropped, so re-scanning is idempotent from the user's point of view.
 */
export async function detectNames(canvas, { known = [], minConfidence = 55 } = {}) {
  const worker = await getWorker();
  const { data } = await worker.recognize(canvas);

  const knownSet = new Set(known.map(normalise));
  const byName = new Map();

  const lines = data.lines?.length
    ? data.lines
    : (data.text || "").split("\n").map((text) => ({ text, confidence: data.confidence ?? 0 }));

  for (const line of lines) {
    // A tile label can be "Rohit Sharma" or "Rohit Sharma (Host)"; strip
    // parenthetical decoration before judging the shape.
    const stripped = (line.text || "").replace(/\([^)]*\)/g, " ");

    for (const piece of stripped.split(/[|•·,•]+/)) {
      const text = piece.trim();
      if (!looksLikeName(text)) continue;

      const confidence = Math.round(line.confidence ?? 0);
      if (confidence < minConfidence) continue;

      const name = tidyName(text);
      const key = normalise(name);
      if (knownSet.has(key)) continue;

      // The same person appears on several frames' worth of tiles; keep
      // the reading OCR was most sure about.
      const existing = byName.get(key);
      if (!existing || confidence > existing.confidence) {
        byName.set(key, { name, confidence });
      }
    }
  }

  return [...byName.values()].sort((a, b) => b.confidence - a.confidence);
}
