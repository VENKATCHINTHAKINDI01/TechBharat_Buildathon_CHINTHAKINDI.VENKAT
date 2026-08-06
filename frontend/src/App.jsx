import { useCallback, useEffect, useMemo, useState } from "react";
import { listMeetings, getReadiness } from "./api/client";
import UploadForm from "./components/UploadForm";
import ReviewScreen from "./components/ReviewScreen";
import LivePanel from "./components/LivePanel";
import MeetingHistory from "./components/MeetingHistory";
import ReportView from "./components/ReportView";
import CommandPalette, { useShortcuts } from "./ui/CommandPalette";
import { ThemeSwitch } from "./ui/theme";
import { useToast } from "./ui/toast";

const TABS = [
  ["upload", "Upload", "Transcript or recording"],
  ["live", "Live meeting", "Capture as it happens"],
  ["history", "Past meetings", "Reports and actions"],
];

export default function App() {
  const [readiness, setReadiness] = useState(null);
  const [offline, setOffline] = useState(false);
  // "upload" | "live" | "history" | "review" | "report"
  const [view, setView] = useState("upload");
  const [meetingId, setMeetingId] = useState(null);
  const [uploadSummary, setUploadSummary] = useState(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [meetings, setMeetings] = useState([]);
  const toast = useToast();

  useEffect(() => {
    getReadiness().then(setReadiness).catch(() => setOffline(true));
  }, []);

  // Meetings are loaded for the palette, not for a screen, so a failure
  // here should cost the palette some entries and nothing else.
  useEffect(() => {
    listMeetings().then(setMeetings).catch(() => setMeetings([]));
  }, [view]);

  const integrations = readiness?.integrations ?? {};
  const mongo = readiness?.mongo;

  const openReview = useCallback((id, summary = null) => {
    setMeetingId(id);
    setUploadSummary(summary);
    setView("review");
  }, []);

  const openReport = useCallback((id) => {
    setMeetingId(id);
    setView("report");
  }, []);

  const go = useCallback((next) => {
    setView(next);
    setMeetingId(null);
    setUploadSummary(null);
  }, []);

  const commands = useMemo(() => {
    const base = [
      { id: "upload", label: "Upload a transcript or recording", icon: "↑", group: "Go", run: () => go("upload") },
      { id: "live", label: "Start a live meeting", icon: "●", group: "Go", run: () => go("live") },
      { id: "history", label: "Past meetings", icon: "⧉", group: "Go", run: () => go("history") },
    ];
    const recent = meetings.slice(0, 8).map((m) => ({
      id: `m-${m.meeting_id}`,
      label: m.title || m.meeting_id,
      icon: "◆",
      group: m.meeting_date,
      keywords: m.meeting_id,
      run: () => openReport(m.meeting_id),
    }));
    return [...base, ...recent];
  }, [meetings, go, openReport]);

  useShortcuts(
    useMemo(
      () => ({
        "mod+k": () => setPaletteOpen((open) => !open),
        "g": () => setPaletteOpen(true),
        "?": () =>
          toast.info(
            "Keyboard shortcuts",
            "⌘K command palette · A approve · R reject · J/K next and previous"
          ),
      }),
      [toast]
    )
  );

  const statusPill = (key, label, warnOnly = false) => (
    <span className={`pill ${integrations[key] ? "ok" : warnOnly ? "warn" : "bad"}`} key={key}>
      {label} {integrations[key] ? "on" : warnOnly ? "fallback" : "off"}
    </span>
  );

  return (
    <div className="app">
      <header className="masthead">
        <span className="naina-dot lg" aria-hidden="true">N</span>
        <h1>Nexvi.Meets</h1>
        <span className="pill accent">commitment integrity, not summarization</span>
        <span className="spacer" />
        <button
          className="ghost tiny"
          onClick={() => setPaletteOpen(true)}
          title="Command palette"
        >
          Search <kbd>⌘K</kbd>
        </button>
        <ThemeSwitch />
      </header>

      <p className="tagline">
        <strong>Naina</strong> sits in your meetings and tracks every commitment as it is made,
        handed over, delayed or dropped. The model interprets the meeting; deterministic code
        decides whether anything leaves this machine.
      </p>

      <div className="status-bar">
        {offline ? (
          <span className="pill bad">backend unreachable</span>
        ) : (
          <>
            <span className="pill ok">backend up</span>
            {/* Reachability, not just configuration -- a set MONGO_URI that
                cannot connect looks identical until the first write. */}
            <span
              className={`pill ${mongo?.connected ? "ok" : mongo?.configured ? "bad" : "warn"}`}
              title={mongo?.detail}
            >
              mongo {mongo?.connected ? "connected" : mongo?.configured ? "unreachable" : "not set"}
            </span>
            {statusPill("groq", "groq", true)}
            {statusPill("github", "github")}
            {statusPill("live_audio", "audio", true)}
            {statusPill("calendar", "calendar", true)}
            {readiness && <span className="pill accent">agents: {readiness.agent_runtime}</span>}
          </>
        )}
      </div>

      {mongo?.configured && !mongo?.connected && (
        <div className="error">
          <strong>The database is unreachable, so nothing can be saved.</strong>
          <div style={{ marginTop: 6, fontSize: 12 }}>{mongo.detail}</div>
        </div>
      )}

      <div className="tabs" role="tablist">
        {TABS.map(([key, label, hint]) => (
          <button
            key={key}
            role="tab"
            title={hint}
            aria-selected={view === key}
            onClick={() => go(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="view-enter" key={`${view}-${meetingId || ""}`}>
        {view === "upload" && (
          <UploadForm onUploaded={(result) => openReview(result.meeting_id, result)} />
        )}

        {view === "live" && <LivePanel onFinished={(id) => openReport(id)} />}

        {view === "history" && (
          <MeetingHistory onOpenReview={openReview} onOpenReport={openReport} />
        )}

        {view === "review" && meetingId && (
          <ReviewScreen
            meetingId={meetingId}
            uploadSummary={uploadSummary}
            onBack={() => go("history")}
            onOpenReport={() => openReport(meetingId)}
          />
        )}

        {view === "report" && meetingId && (
          <ReportView
            meetingId={meetingId}
            onBack={() => go("history")}
            onOpenReview={(id) => openReview(id)}
          />
        )}
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
      />
    </div>
  );
}
