import { useEffect, useState } from "react";
import { checkHealth } from "./services/api";
import MeetingUpload from "./components/MeetingUpload";
import ReviewScreen from "./components/ReviewScreen";

// Phase 6+ will add: LiveCapturePanel, LiveTranscriptFeed, AuditLogView
export default function App() {
  const [backendStatus, setBackendStatus] = useState("checking...");
  const [meetingId, setMeetingId] = useState(null);

  useEffect(() => {
    checkHealth()
      .then((data) => setBackendStatus(`connected — ${data.app} (${data.environment})`))
      .catch(() => setBackendStatus("backend unreachable"));
  }, []);

  return (
    <div style={{ fontFamily: "sans-serif", padding: "2rem", maxWidth: 720, margin: "0 auto" }}>
      <h1>NexVi.Meets</h1>
      <p style={{ fontSize: 12, color: "#888" }}>Backend: {backendStatus}</p>

      {!meetingId ? (
        <MeetingUpload onUploaded={setMeetingId} />
      ) : (
        <>
          <button onClick={() => setMeetingId(null)} style={{ marginBottom: 16 }}>
            &larr; Upload another meeting
          </button>
          <ReviewScreen meetingId={meetingId} />
        </>
      )}
    </div>
  );
}