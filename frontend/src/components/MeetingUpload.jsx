import { useState } from "react";
import { uploadMeeting } from "../services/api";

export default function MeetingUpload({ onUploaded }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [meetingDate, setMeetingDate] = useState(new Date().toISOString().slice(0, 10));
  const [calendarEventId, setCalendarEventId] = useState("");
  const [manualAttendees, setManualAttendees] = useState("");
  const [status, setStatus] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file || !title) return;
    setStatus("Processing — this runs the full extraction pipeline, may take a few seconds…");
    try {
      const result = await uploadMeeting(
        file,
        title,
        meetingDate,
        calendarEventId || null,
        manualAttendees || null
      );
      setStatus(`Done — ${result.action_items_saved} action items extracted.`);
      onUploaded(result.meeting_id);
    } catch (err) {
      setStatus(`Failed: ${err?.response?.data?.detail || err.message}`);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ marginBottom: 24 }}>
      <div>
        <input placeholder="Meeting title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div>
        <input type="date" value={meetingDate} onChange={(e) => setMeetingDate(e.target.value)} />
      </div>
      <div>
        <input type="file" accept=".txt,.vtt,.srt" onChange={(e) => setFile(e.target.files[0])} />
      </div>

      <fieldset style={{ marginTop: 12, border: "1px solid #ddd", borderRadius: 6 }}>
        <legend style={{ fontSize: 13, color: "#666" }}>Attendee roster (pick one)</legend>
        <div>
          <label style={{ fontSize: 13 }}>
            Google Calendar event ID:{" "}
            <input
              value={calendarEventId}
              onChange={(e) => setCalendarEventId(e.target.value)}
              placeholder="pulls real attendee list"
            />
          </label>
        </div>
        <div style={{ marginTop: 6 }}>
          <label style={{ fontSize: 13 }}>
            Or type attendees manually, one per line:
            <br />
            <textarea
              rows={3}
              style={{ width: "100%" }}
              value={manualAttendees}
              onChange={(e) => setManualAttendees(e.target.value)}
              placeholder={"Priya Sharma <priya@x.com>\nRahul <rahul@x.com>"}
            />
          </label>
        </div>
      </fieldset>

      <button type="submit" style={{ marginTop: 12 }}>Upload & extract</button>
      {status && <p>{status}</p>}
    </form>
  );
}