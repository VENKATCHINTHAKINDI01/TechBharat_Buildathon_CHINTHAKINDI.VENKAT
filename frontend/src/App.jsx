import { useEffect, useState } from "react";
import { getReadiness } from "./api/client";
import UploadForm from "./components/UploadForm";
import ReviewScreen from "./components/ReviewScreen";
import LivePanel from "./components/LivePanel";
import MeetingHistory from "./components/MeetingHistory";
import ReportView from "./components/ReportView";

export default function App() {
  const [readiness, setReadiness] = useState(null);
  const [offline, setOffline] = useState(false);
  // "upload" | "live" | "history" | "review" | "report"
  const [view, setView] = useState("upload");
  const [meetingId, setMeetingId] = useState(null);
  const [uploadSummary, setUploadSummary] = useState(null);

  useEffect(() => {
    getReadiness().then(setReadiness).catch(() => setOffline(true));
  }, []);

  const integrations = readiness?.integrations ?? {};
  const mongo = readiness?.mongo;

  const pill = (key, label, warnOnly = false) => (
    <span className={`pill ${integrations[key] ? "ok" : warnOnly ? "warn" : "bad"}`} key={key}>
      {label} {integrations[key] ? "on" : warnOnly ? "fallback" : "off"}
    </span>
  );

  function openReview(id, summary = null) {
    setMeetingId(id);
    setUploadSummary(summary);
    setView("review");
  }

  function openReport(id) {
    setMeetingId(id);
    setView("report");
  }

  const tabs = [
    ["upload", "Upload transcript"],
    ["live", "Live meeting"],
    ["history", "Past meetings"],
  ];

  return (
    <div className="app">
      <header className="masthead">
        <span className="naina-dot lg" aria-hidden="true">N</span>
        <h1>Nexvi.Meets</h1>
        <span className="pill accent">commitment integrity, not summarization</span>
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
            {pill("groq", "groq", true)}
            {pill("github", "github")}
            {pill("live_audio", "audio", true)}
            {pill("calendar", "calendar", true)}
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

      <div className="actions" style={{ marginBottom: 16 }}>
        {tabs.map(([key, label]) => (
          <button
            key={key}
            className={view === key ? "primary" : "ghost"}
            onClick={() => {
              setView(key);
              setMeetingId(null);
              setUploadSummary(null);
            }}
          >
            {label}
          </button>
        ))}
      </div>

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
          onBack={() => setView("history")}
          onOpenReport={() => openReport(meetingId)}
        />
      )}

      {view === "report" && meetingId && (
        <ReportView
          meetingId={meetingId}
          onBack={() => setView("history")}
          onOpenReview={(id) => openReview(id)}
        />
      )}
    </div>
  );
}
