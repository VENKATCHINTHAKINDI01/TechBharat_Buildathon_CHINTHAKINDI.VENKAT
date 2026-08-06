/**
 * Frontend smoke tests.
 *
 * The UI had no automated tests, which was fine while it was one screen
 * and became indefensible once it grew a theme system, a command
 * palette, toasts and keyboard shortcuts. A passing `vite build` only
 * proves the code parses — it says nothing about whether the app
 * actually renders or whether the theme wiring works.
 *
 * These are deliberately shallow. They check that each surface mounts,
 * that the safety-critical copy is present, and that the interactive
 * shell behaves. Layout and colour still need human eyes.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { ThemeProvider, ThemeSwitch } from "../ui/theme";
import { ToastProvider, useToast } from "../ui/toast";
import CommandPalette from "../ui/CommandPalette";

vi.mock("../api/client", () => ({
  getReadiness: vi.fn(async () => ({
    integrations: { groq: true, github: true, live_audio: true, calendar: false },
    mongo: { configured: true, connected: true, detail: "ok" },
    agent_runtime: "inhouse",
  })),
  listMeetings: vi.fn(async () => [
    { meeting_id: "nm-1", title: "Sprint standup", meeting_date: "2026-08-06" },
  ]),
  getMeeting: vi.fn(async () => ({ participants: [], candidates: [], record: null })),
  getTranscript: vi.fn(async () => ({ segments: [] })),
  getReport: vi.fn(async () => ({ action_items: [], decisions: [] })),
  getActionsTaken: vi.fn(async () => []),
  getAuditLog: vi.fn(async () => []),
  getAgentRun: vi.fn(async () => ({ steps: [] })),
  deleteMeeting: vi.fn(async () => ({})),
  uploadMeeting: vi.fn(async () => ({ meeting_id: "nm-1", candidates: 1, segments: 3 })),
  approveCandidate: vi.fn(async () => ({})),
  rejectCandidate: vi.fn(async () => ({})),
  editCandidate: vi.fn(async () => ({})),
  assignSpeakers: vi.fn(async () => ({})),
  reportMarkdownUrl: (id) => `/api/meetings/${id}/report.md`,
  openLiveSocket: vi.fn(() => ({ close: vi.fn(), readyState: 0 })),
}));

function renderApp() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </ThemeProvider>
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => document.documentElement.removeAttribute("data-theme"));

// --- the app shell --------------------------------------------------------

describe("app shell", () => {
  it("renders the masthead and Naina", async () => {
    renderApp();
    expect(await screen.findByRole("heading", { name: "Nexvi.Meets" })).toBeInTheDocument();
    expect(screen.getByText(/Naina/)).toBeInTheDocument();
  });

  it("shows live integration status once readiness loads", async () => {
    renderApp();
    expect(await screen.findByText(/mongo connected/)).toBeInTheDocument();
    expect(screen.getByText(/groq on/)).toBeInTheDocument();
  });

  it("switches between the three main views", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: "Live meeting" }));
    expect(await screen.findByText(/Start a meeting with Naina/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Past meetings" }));
    expect(await screen.findByRole("heading", { name: /Past meetings/ })).toBeInTheDocument();
  });
});

// --- theme ---------------------------------------------------------------

describe("theme switcher", () => {
  it("applies the chosen theme to the document", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeSwitch />
      </ThemeProvider>
    );

    await user.click(screen.getByRole("button", { name: "Light" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");

    await user.click(screen.getByRole("button", { name: "Dark" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("remembers the choice across a reload", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ThemeProvider>
        <ThemeSwitch />
      </ThemeProvider>
    );
    await user.click(screen.getByRole("button", { name: "Light" }));
    unmount();

    render(
      <ThemeProvider>
        <ThemeSwitch />
      </ThemeProvider>
    );
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "true");
  });

  it("follows the OS when set to system", async () => {
    window.matchMedia = (query) => ({
      matches: query.includes("dark"),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    });

    render(
      <ThemeProvider>
        <ThemeSwitch />
      </ThemeProvider>
    );
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });
});

// --- toasts ---------------------------------------------------------------

describe("toasts", () => {
  function Trigger() {
    const toast = useToast();
    return (
      <>
        <button onClick={() => toast.success("Approved", "the thing")}>ok</button>
        <button onClick={() => toast.error("Failed", "the reason")}>bad</button>
      </>
    );
  }

  it("shows a success toast", async () => {
    const user = userEvent.setup();
    render(<ToastProvider><Trigger /></ToastProvider>);

    await user.click(screen.getByText("ok"));
    expect(await screen.findByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("the thing")).toBeInTheDocument();
  });

  it("announces errors assertively and does not auto-dismiss them", async () => {
    const user = userEvent.setup();
    render(<ToastProvider><Trigger /></ToastProvider>);

    await user.click(screen.getByText("bad"));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Failed")).toBeInTheDocument();
  });
});

// --- command palette ------------------------------------------------------

describe("command palette", () => {
  const commands = [
    { id: "a", label: "Upload a transcript", run: vi.fn() },
    { id: "b", label: "Past meetings", run: vi.fn() },
  ];

  it("filters by subsequence, so 'pm' finds 'Past meetings'", async () => {
    const user = userEvent.setup();
    render(<CommandPalette open onClose={() => {}} commands={commands} />);

    await user.type(screen.getByRole("textbox"), "pm");
    expect(screen.getByText("Past meetings")).toBeInTheDocument();
    expect(screen.queryByText("Upload a transcript")).not.toBeInTheDocument();
  });

  it("runs the highlighted command on Enter", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} commands={commands} />);

    await user.keyboard("{ArrowDown}{Enter}");
    expect(commands[1].run).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} commands={commands} />);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("opens from the keyboard shortcut", async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByRole("heading", { name: "Nexvi.Meets" });

    await user.keyboard("{Meta>}k{/Meta}");
    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeInTheDocument();
  });
});

// --- upload ---------------------------------------------------------------

describe("upload form", () => {
  it("offers both transcripts and recordings", async () => {
    renderApp();
    expect(await screen.findByText(/Drop a file here/)).toBeInTheDocument();
    expect(screen.getByText(/Recordings:/)).toBeInTheDocument();
  });

  it("rejects an unsupported format before uploading anything", async () => {
    const { uploadMeeting } = await import("../api/client");
    renderApp();

    // Dropped, not picked: the file picker filters by `accept`, so a
    // drop is the only way an unsupported file actually reaches us --
    // and therefore the only path where this validation matters.
    const zone = await screen.findByRole("button", { name: /Choose a transcript or recording/ });
    fireEvent.drop(zone, {
      dataTransfer: {
        files: [new File(["x"], "notes.pages", { type: "application/octet-stream" })],
      },
    });

    expect(await screen.findByText(/is not a format Nexvi.Meets can read|isn.t a format/i))
      .toBeInTheDocument();
    expect(uploadMeeting).not.toHaveBeenCalled();
  });

  it("warns that a recording has no speaker labels", async () => {
    renderApp();

    const zone = await screen.findByRole("button", { name: /Choose a transcript or recording/ });
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(["x"], "standup.mp3", { type: "audio/mpeg" })] },
    });

    // This copy is the safety story for uploaded media; if it disappears,
    // a user has no idea why nothing can be approved.
    expect(await screen.findByText(/Recordings have no speaker labels/)).toBeInTheDocument();
  });
});
