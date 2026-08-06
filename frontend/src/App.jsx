import { useEffect, useState } from "react";
import { getReadiness } from "./api/client";
import UploadForm from "./components/UploadForm";
import ReviewScreen from "./components/ReviewScreen";
import LivePanel from "./components/LivePanel";

export default function App() {
  const [readiness, setReadiness] = useState(null);
  const [offline, setOffline] = useState(false);
  const [upload, setUpload] = useState(null);
  const [mode, setMode] = useState("upload"); // "upload" | "live"

  useEffect(() => {
    getReadiness().then(setReadiness).catch(() => setOffline(true));
  }, []);

  const integrations = readiness?.integrations ?? {};

  const pill = (key, label, warnOnly = false) => (
    <span className={`pill ${integrations[key] ? "ok" : warnOnly ? "warn" : "bad"}`} key={key}>
      {label} {integrations[key] ? "on" : warnOnly ? "fallback" : "off"}
    </span>
  );

  return (
    <div className="app">
      <header className="masthead">
        <h1>Nexvi.Meets</h1>
        <span className="pill accent">commitment integrity, not summarization</span>
      </header>
      <p className="tagline">
        The model interprets the meeting. Deterministic code decides whether anything leaves this
        machine.
      </p>

      <div className="status-bar">
        {offline ? (
          <span className="pill bad">backend unreachable</span>
        ) : (
          <>
            <span className="pill ok">backend up</span>
            {pill("mongo", "mongo")}
            {pill("groq", "groq", true)}
            {pill("github", "github")}
            {pill("calendar", "calendar", true)}
            {pill("sarvam", "sarvam", true)}
            {readiness && <span className="pill accent">agents: {readiness.agent_runtime}</span>}
            {readiness && <span className="pill">threshold {readiness.confidence_threshold}</span>}
          </>
        )}
      </div>

      {!upload && (
        <div className="actions" style={{ marginBottom: 16 }}>
          <button
            className={mode === "upload" ? "primary" : "ghost"}
            onClick={() => setMode("upload")}
          >
            Upload transcript
          </button>
          <button className={mode === "live" ? "primary" : "ghost"} onClick={() => setMode("live")}>
            Live meeting
          </button>
        </div>
      )}

      {upload ? (
        <ReviewScreen
          meetingId={upload.meeting_id}
          uploadSummary={upload}
          onBack={() => setUpload(null)}
        />
      ) : mode === "upload" ? (
        <UploadForm onUploaded={setUpload} />
      ) : (
        <LivePanel onFinished={(meetingId) => setUpload({ meeting_id: meetingId })} />
      )}
    </div>
  );
}
