import { useEffect, useState } from "react";
import { getReadiness } from "./api/client";
import UploadForm from "./components/UploadForm";
import ReviewScreen from "./components/ReviewScreen";

export default function App() {
  const [readiness, setReadiness] = useState(null);
  const [offline, setOffline] = useState(false);
  const [upload, setUpload] = useState(null);

  useEffect(() => {
    getReadiness().then(setReadiness).catch(() => setOffline(true));
  }, []);

  const integrations = readiness?.integrations ?? {};

  return (
    <div className="app">
      <header className="masthead">
        <h1>CommitGuard</h1>
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
            <span className={`pill ${integrations.mongo ? "ok" : "bad"}`}>
              mongo {integrations.mongo ? "configured" : "missing"}
            </span>
            <span className={`pill ${integrations.groq ? "ok" : "warn"}`}>
              groq {integrations.groq ? "configured" : "fallback"}
            </span>
            <span className={`pill ${integrations.github ? "ok" : "bad"}`}>
              github {integrations.github ? "configured" : "missing"}
            </span>
            {readiness && (
              <span className="pill">threshold {readiness.confidence_threshold}</span>
            )}
          </>
        )}
      </div>

      {!upload ? (
        <UploadForm onUploaded={setUpload} />
      ) : (
        <ReviewScreen
          meetingId={upload.meeting_id}
          uploadSummary={upload}
          onBack={() => setUpload(null)}
        />
      )}
    </div>
  );
}
