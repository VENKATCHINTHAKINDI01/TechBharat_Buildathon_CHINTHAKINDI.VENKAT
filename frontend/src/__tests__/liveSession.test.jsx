/**
 * A meeting must survive navigation.
 *
 * The live session used to live inside `LivePanel`. Because the app
 * renders `{view === "live" && <LivePanel/>}`, opening "Past meetings"
 * mid-meeting unmounted the panel, and its cleanup closed the websocket
 * and stopped the microphone. **The recording ended silently.** Nothing
 * in the UI said so; you came back to a dead session and a partial
 * transcript.
 *
 * The session now lives above the view switch. These tests hold that
 * line, because it is the kind of bug that only shows up when someone
 * clicks away mid-demo — which is exactly when it costs most.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { LiveSessionProvider } from "../live/LiveSessionProvider";
import { ThemeProvider } from "../ui/theme";
import { ToastProvider } from "../ui/toast";

// --- a controllable fake socket ------------------------------------------

class FakeSocket {
  static last = null;

  constructor() {
    this.readyState = 1; // OPEN
    this.sent = [];
    this.closed = false;
    FakeSocket.last = this;
  }

  send(payload) {
    this.sent.push(JSON.parse(payload));
  }

  close() {
    this.closed = true;
  }

  /** Push a server message into the app. */
  emit(message) {
    act(() => this.onmessage?.({ data: JSON.stringify(message) }));
  }

  open() {
    act(() => this.onopen?.());
  }
}

const stopped = { count: 0 };

vi.mock("../lib/audioCapture", () => ({
  isCaptureSupported: () => true,
  tabAudioSupport: () => ({ supported: true, browser: "Chrome" }),
  captureMicrophone: vi.fn(async () => ({ getTracks: () => [], getAudioTracks: () => [] })),
  captureTabAudio: vi.fn(async ({ keepVideo } = {}) => ({
    audio: { getTracks: () => [], getAudioTracks: () => [] },
    video: keepVideo ? { getTracks: () => [], getVideoTracks: () => [{ stop() {} }] } : null,
  })),
  grabFrame: vi.fn(async () => ({ width: 1280, height: 720 })),
  TrackRecorder: class {
    start() {}
    pause() {}
    resume() {}
    stop() {
      stopped.count += 1;
    }
  },
}));

vi.mock("../api/client", () => ({
  getReadiness: vi.fn(async () => ({ integrations: {}, mongo: {}, agent_runtime: "inhouse" })),
  listMeetings: vi.fn(async () => []),
  getMeeting: vi.fn(async () => ({ participants: [], candidates: [], record: null })),
  getTranscript: vi.fn(async () => ({ segments: [] })),
  getReport: vi.fn(async () => ({ action_items: [], decisions: [] })),
  getActionsTaken: vi.fn(async () => []),
  getAuditLog: vi.fn(async () => []),
  getAgentRun: vi.fn(async () => ({ steps: [] })),
  deleteMeeting: vi.fn(async () => ({})),
  uploadMeeting: vi.fn(async () => ({})),
  approveCandidate: vi.fn(async () => ({})),
  rejectCandidate: vi.fn(async () => ({})),
  editCandidate: vi.fn(async () => ({})),
  assignSpeakers: vi.fn(async () => ({})),
  reportMarkdownUrl: (id) => `/api/meetings/${id}/report.md`,
  openLiveSocket: vi.fn(() => new FakeSocket()),
}));

function renderApp() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <LiveSessionProvider>
          <App />
        </LiveSessionProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}

/** Walk through setup and get to a running meeting. */
async function startMeeting(user) {
  await user.click(await screen.findByRole("tab", { name: "Live meeting" }));
  await screen.findByText(/Start a meeting with Naina/);

  await user.click(screen.getByRole("checkbox", { name: /Everyone in this meeting knows/ }));
  await user.click(screen.getByRole("button", { name: /Start capturing/ }));

  await waitFor(() => expect(FakeSocket.last).toBeTruthy());
  FakeSocket.last.open();
  FakeSocket.last.emit({
    type: "started",
    meeting_id: "nm-live-1",
    participants: [{ participant_id: "p-rohit", name: "Rohit" }],
    transcriber: "groq_whisper",
    audio_enabled: true,
    chunk_seconds: 6,
  });
  return FakeSocket.last;
}

beforeEach(() => {
  stopped.count = 0;
  FakeSocket.last = null;
  localStorage.clear();
});
afterEach(() => vi.clearAllMocks());

describe("a live meeting survives navigation", () => {
  it("keeps the socket open and the recorders running when you change tabs", async () => {
    const user = userEvent.setup();
    renderApp();
    const socket = await startMeeting(user);

    await user.click(screen.getByRole("tab", { name: "Past meetings" }));
    await screen.findByRole("heading", { name: /Past meetings/ });

    expect(socket.closed).toBe(false);
    expect(stopped.count).toBe(0);
  });

  it("shows Naina's bar on the meetings tab, with working controls", async () => {
    const user = userEvent.setup();
    renderApp();
    const socket = await startMeeting(user);

    await user.click(screen.getByRole("tab", { name: "Past meetings" }));
    await screen.findByRole("heading", { name: /Past meetings/ });

    // The bar is still there, on a different screen.
    expect(screen.getByRole("complementary", { name: /Naina/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Pause/ }));
    expect(socket.sent.some((m) => m.type === "pause")).toBe(true);
  });

  it("can end the meeting from another tab", async () => {
    const user = userEvent.setup();
    renderApp();
    const socket = await startMeeting(user);

    await user.click(screen.getByRole("tab", { name: "Upload" }));
    await screen.findByText(/Drop a file here/);

    await user.click(screen.getByRole("button", { name: /End/ }));
    expect(socket.sent.some((m) => m.type === "end")).toBe(true);
  });

  it("keeps the transcript across a round trip to another tab", async () => {
    const user = userEvent.setup();
    renderApp();
    const socket = await startMeeting(user);

    socket.emit({
      type: "segments",
      segments: [
        {
          segment_id: "s1",
          speaker: "Rohit",
          text: "I will finish the API migration by Friday.",
          track: "mic",
          start_ms: 0,
          attributable: true,
        },
      ],
    });

    await user.click(screen.getByRole("tab", { name: "Past meetings" }));
    await user.click(screen.getByRole("tab", { name: "Live meeting" }));

    // Present twice over: in the panel transcript and in the floating bar.
    const lines = await screen.findAllByText(/I will finish the API migration by Friday/);
    expect(lines.length).toBeGreaterThan(0);
  });

  it("warns in the masthead that recording is still running", async () => {
    const user = userEvent.setup();
    renderApp();
    await startMeeting(user);

    await user.click(screen.getByRole("tab", { name: "Past meetings" }));
    // Leaving a meeting recording by accident is the failure this guards.
    expect(await screen.findByRole("button", { name: /Recording/ })).toBeInTheDocument();
  });

  it("offers a way back to the meeting from the bar", async () => {
    const user = userEvent.setup();
    renderApp();
    await startMeeting(user);

    await user.click(screen.getByRole("tab", { name: "Past meetings" }));
    await user.click(await screen.findByRole("button", { name: /Open meeting/ }));

    expect(await screen.findByRole("heading", { name: /Live meeting/ })).toBeInTheDocument();
  });

  it("hides the bar entirely on request, and puts it back", async () => {
    const user = userEvent.setup();
    renderApp();
    await startMeeting(user);
    await user.click(screen.getByRole("tab", { name: "Past meetings" }));

    await user.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByRole("complementary", { name: /Naina/i })).not.toBeInTheDocument();

    // The masthead pill is the remaining signal that a meeting is live.
    expect(screen.getByRole("button", { name: /Recording/ })).toBeInTheDocument();
  });

  it("stops showing the bar once the meeting has ended", async () => {
    const user = userEvent.setup();
    renderApp();
    const socket = await startMeeting(user);

    socket.emit({ type: "ended", meeting_id: "nm-live-1", segments: [], candidates: [] });

    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: /Naina/i })).not.toBeInTheDocument()
    );
  });
});

// --- names read off the shared screen -------------------------------------
//
// A name on a video tile is a guess in a confident font. These tests hold
// the line that it stays a *proposal* until a human says yes, because a
// wrong one would become an owner the safety gate happily approves.

describe("detected participant names", () => {
  async function startWithScreen(user) {
    await user.click(await screen.findByRole("tab", { name: "Live meeting" }));
    await screen.findByText(/Start a meeting with Naina/);

    await user.click(screen.getByRole("checkbox", { name: /Let Naina read participant names/ }));
    await user.click(screen.getByRole("checkbox", { name: /Everyone in this meeting knows/ }));
    await user.click(screen.getByRole("button", { name: /Start capturing/ }));

    await waitFor(() => expect(FakeSocket.last).toBeTruthy());
    FakeSocket.last.open();
    FakeSocket.last.emit({
      type: "started",
      meeting_id: "nm-live-2",
      participants: [{ participant_id: "p-arjun", name: "Arjun" }],
      audio_enabled: true,
      chunk_seconds: 6,
    });
    return FakeSocket.last;
  }

  it("offers the scan control only after you opt in", async () => {
    const user = userEvent.setup();
    renderApp();
    await startWithScreen(user);

    // Offered in both the live panel and the floating bar, exactly as
    // the transcript and the commitments already are.
    expect(
      await screen.findAllByRole("button", { name: /Find names on screen/ })
    ).not.toHaveLength(0);
  });

  it("keeps screen reading off unless explicitly enabled", async () => {
    const user = userEvent.setup();
    renderApp();

    // Same flow, but without ticking the screen-reading box.
    await user.click(await screen.findByRole("tab", { name: "Live meeting" }));
    await screen.findByText(/Start a meeting with Naina/);
    await user.click(screen.getByRole("checkbox", { name: /Everyone in this meeting knows/ }));
    await user.click(screen.getByRole("button", { name: /Start capturing/ }));
    await waitFor(() => expect(FakeSocket.last).toBeTruthy());
    FakeSocket.last.open();
    FakeSocket.last.emit({
      type: "started", meeting_id: "nm-live-3", participants: [], audio_enabled: true,
    });

    expect(screen.queryByRole("button", { name: /Find names on screen/ })).not.toBeInTheDocument();
  });

  it("sends nothing to the server until a name is accepted", async () => {
    const user = userEvent.setup();
    renderApp();
    const socket = await startWithScreen(user);

    // A proposal exists in the UI but has not been confirmed.
    act(() => {
      socket.emit({ type: "warnings", warnings: [] });
    });

    expect(socket.sent.some((m) => m.type === "add_participants")).toBe(false);
  });

  it("adds a confirmed name to the roster and marks its source", async () => {
    const user = userEvent.setup();
    renderApp();
    const socket = await startWithScreen(user);

    // The server confirms; the roster grows.
    socket.emit({
      type: "participants",
      added: [{ participant_id: "p-mahesh", name: "Mahesh" }],
      participants: [
        { participant_id: "p-arjun", name: "Arjun" },
        { participant_id: "p-mahesh", name: "Mahesh" },
      ],
    });

    // The roster count is what the user actually sees change.
    await waitFor(() => expect(screen.getAllByText(/2 in the room/).length).toBeGreaterThan(0));
  });
});
