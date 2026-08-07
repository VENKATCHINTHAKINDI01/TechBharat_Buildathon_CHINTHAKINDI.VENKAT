/**
 * Reading names off the meeting screen.
 *
 * The filtering is the whole feature. OCR on a video call returns a
 * soup of tile labels, button captions, connection warnings and device
 * names, and only some of it is people. Everything that gets through
 * becomes a name a human is invited to accept as someone who can own
 * work — so the bar for getting through is deliberately high.
 *
 * The asymmetry drives the design: a false positive risks a wrong owner
 * on a real GitHub issue; a false negative costs one typed name.
 */
import { describe, expect, it, vi } from "vitest";
import { detectNames, looksLikeName, tidyName } from "../lib/nameDetection";

// --- what counts as a name ------------------------------------------------

describe("looksLikeName", () => {
  it("accepts ordinary personal names", () => {
    for (const name of [
      "Rohit", "Rohit Sharma", "Meera Nair", "Arjun", "Priya Raghunathan",
      "Jean-Luc Picard", "O'Brien", "Anne Marie Smith",
    ]) {
      expect(looksLikeName(name), name).toBe(true);
    }
  });

  it("rejects the interface furniture OCR always picks up", () => {
    for (const noise of [
      "You", "Host", "Presenting", "Muted", "Chat", "Participants",
      "Leave call", "Recording", "Turn on captions", "Poor connection",
    ]) {
      expect(looksLikeName(noise), noise).toBe(false);
    }
  });

  it("rejects device and room names, which are not people", () => {
    // These join real meetings constantly and would become owners.
    for (const device of [
      "iPhone", "Ravi's MacBook", "Conference Room 2", "Meeting Room",
      "Galaxy S24", "Living Room TV",
    ]) {
      expect(looksLikeName(device), device).toBe(false);
    }
  });

  it("rejects anything with digits", () => {
    expect(looksLikeName("Room 4")).toBe(false);
    expect(looksLikeName("User123")).toBe(false);
  });

  it("rejects OCR garbage", () => {
    for (const junk of ["", "  ", "!!", "a", "|||", "— — —", "x".repeat(60)]) {
      expect(looksLikeName(junk), JSON.stringify(junk)).toBe(false);
    }
  });

  it("rejects a lone all-caps word, which is nearly always a label", () => {
    expect(looksLikeName("PRESENTING")).toBe(false);
    expect(looksLikeName("LIVE")).toBe(false);
  });

  it("rejects a sentence — names are not four words of prose", () => {
    expect(looksLikeName("is presenting their screen right now")).toBe(false);
  });
});

describe("tidyName", () => {
  it("normalises the casing OCR returns", () => {
    expect(tidyName("  rohit   SHARMA ")).toBe("Rohit Sharma");
    expect(tidyName("MEERA")).toBe("Meera");
  });
});

// --- the detection pass ---------------------------------------------------

function fakeWorker(lines) {
  return {
    recognize: vi.fn(async () => ({
      data: { lines, text: lines.map((l) => l.text).join("\n"), confidence: 90 },
    })),
    terminate: vi.fn(async () => {}),
  };
}

vi.mock("tesseract.js", () => ({
  createWorker: vi.fn(async () => globalThis.__fakeWorker),
}));

async function run(lines, options) {
  globalThis.__fakeWorker = fakeWorker(lines);
  // The module memoises its worker, so reset it between cases.
  vi.resetModules();
  const { detectNames: fresh } = await import("../lib/nameDetection");
  return fresh({}, options);
}

describe("detectNames", () => {
  it("pulls people out of a realistic Meet frame", async () => {
    const found = await run([
      { text: "Arjun Menon", confidence: 92 },
      { text: "You", confidence: 96 },
      { text: "Rohit Sharma (Host)", confidence: 88 },
      { text: "Presenting", confidence: 94 },
      { text: "Meera Nair", confidence: 81 },
      { text: "iPhone", confidence: 90 },
      { text: "Turn on captions", confidence: 77 },
    ]);

    expect(found.map((f) => f.name)).toEqual(["Arjun Menon", "Rohit Sharma", "Meera Nair"]);
  });

  it("strips parenthetical decoration like (Host)", async () => {
    const found = await run([{ text: "Priya Raghunathan (Co-host)", confidence: 90 }]);
    expect(found[0].name).toBe("Priya Raghunathan");
  });

  it("drops readings OCR was not confident about", async () => {
    const found = await run(
      [
        { text: "Rohit Sharma", confidence: 90 },
        { text: "Mccra Nair", confidence: 30 }, // a mangled read
      ],
      { minConfidence: 55 }
    );
    expect(found.map((f) => f.name)).toEqual(["Rohit Sharma"]);
  });

  it("does not re-propose someone already in the meeting", async () => {
    // Re-scanning must be idempotent, or every scan adds duplicates.
    const found = await run([{ text: "Rohit Sharma", confidence: 90 }], {
      known: ["rohit sharma"],
    });
    expect(found).toEqual([]);
  });

  it("keeps the most confident reading of a repeated tile", async () => {
    const found = await run([
      { text: "Meera Nair", confidence: 62 },
      { text: "meera nair", confidence: 91 },
    ]);
    expect(found).toHaveLength(1);
    expect(found[0].confidence).toBe(91);
  });

  it("returns the most confident names first", async () => {
    const found = await run([
      { text: "Arjun Menon", confidence: 70 },
      { text: "Rohit Sharma", confidence: 95 },
    ]);
    expect(found.map((f) => f.name)).toEqual(["Rohit Sharma", "Arjun Menon"]);
  });

  it("returns nothing rather than guessing when the frame is all furniture", async () => {
    const found = await run([
      { text: "Muted", confidence: 99 },
      { text: "Leave call", confidence: 98 },
      { text: "Recording", confidence: 97 },
    ]);
    expect(found).toEqual([]);
  });
});
