import { useState } from "react";
import { uploadMeeting } from "../api/client";

const DEFAULT_PARTICIPANTS = "Arjun\nRohit\nMeera\nPriya";

export default function UploadForm({ onUploaded }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("Sprint standup");
  const [meetingDate, setMeetingDate] = useState("2026-08-05");
  const [participants, setParticipants] = useState(DEFAULT_PARTICIPANTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (!file) {
      setError("Choose a .txt, .vtt or .srt transcript first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await uploadMeeting({ file, title, meetingDate, participants });
      onUploaded(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Upload transcript</h2>
      {error && <div className="error">{error}</div>}

      <div className="field">
        <label htmlFor="file">Transcript file (.txt, .vtt, .srt)</label>
        <input
          id="file"
          type="file"
          accept=".txt,.vtt,.srt"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="title">Meeting title</label>
          <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="date">Meeting date</label>
          <input
            id="date"
            type="date"
            value={meetingDate}
            onChange={(e) => setMeetingDate(e.target.value)}
            required
          />
        </div>
      </div>

      <div className="field">
        <label htmlFor="participants">
          Participants — one per line as <code>Name &lt;email&gt;</code>, or a JSON array
        </label>
        <textarea
          id="participants"
          value={participants}
          onChange={(e) => setParticipants(e.target.value)}
        />
        <p className="muted" style={{ marginTop: 6 }}>
          Owner resolution fails closed: a name that isn’t in this list, or one that matches two
          people, resolves to nothing rather than being guessed.
        </p>
      </div>

      <button className="primary" type="submit" disabled={busy}>
        {busy ? "Processing…" : "Analyse meeting"}
      </button>
    </form>
  );
}
