import { useEffect, useState } from "react";
import { listMeetings } from "../api/client";

/**
 * Every meeting this workspace has seen, newest first.
 *
 * Counts come pre-aggregated from the server — rendering a list of fifty
 * meetings by fetching each one's detail would be fifty round trips.
 */
export default function MeetingHistory({ onOpenReview, onOpenReport }) {
  const [meetings, setMeetings] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listMeetings()
      .then(setMeetings)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!meetings) return <p className="muted">Loading meetings…</p>;

  if (meetings.length === 0) {
    return (
      <section className="panel">
        <h2>Past meetings</h2>
        <p className="muted">
          Nothing yet. Upload a transcript or run a live meeting, and it will appear here with its
          report and everything that was actioned.
        </p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>Past meetings ({meetings.length})</h2>
      {meetings.map((m) => {
        const pending = Math.max(0, (m.action_items || 0) - (m.reviewed || 0));
        return (
          <div className="meeting-row" key={m.meeting_id}>
            <div className="grow">
              <h3>{m.title || "Untitled meeting"}</h3>
              <div className="meta" style={{ marginTop: 6, marginBottom: 0 }}>
                <span className="pill">{m.meeting_date}</span>
                <span className="pill" title="Meeting ID">
                  {m.meeting_id}
                </span>
                {m.segments > 0 && <span className="pill">{m.segments} lines</span>}
                <span className="pill accent">{m.action_items || 0} action items</span>
                {m.issues_created > 0 && (
                  <span className="pill ok">{m.issues_created} issue(s) created</span>
                )}
                {m.calendar_events > 0 && (
                  <span className="pill ok">{m.calendar_events} invite(s)</span>
                )}
                {pending > 0 && <span className="pill warn">{pending} awaiting review</span>}
              </div>
            </div>
            <button className="ghost" onClick={() => onOpenReport(m.meeting_id)}>
              Report
            </button>
            <button className="primary" onClick={() => onOpenReview(m.meeting_id)}>
              {pending > 0 ? "Review & approve" : "Open"}
            </button>
          </div>
        );
      })}
    </section>
  );
}
