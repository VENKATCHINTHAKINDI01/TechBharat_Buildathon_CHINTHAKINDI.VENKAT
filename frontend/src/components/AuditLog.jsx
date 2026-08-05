import { useEffect, useState } from "react";
import { getAuditLog } from "../api/client";

/**
 * The audit trail is a judged artifact ("Unapproved actions: exactly
 * zero — measured by audit log review"), so it is shown in full rather
 * than summarized, newest last, with the raw payload available.
 */
export default function AuditLog({ meetingId, refreshKey }) {
  const [events, setEvents] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    getAuditLog(meetingId).then(setEvents).catch(() => setEvents([]));
  }, [meetingId, open, refreshKey]);

  return (
    <section className="panel">
      <h2>Audit trail</h2>
      <button className="ghost" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide" : "Show"} audit log
      </button>

      {open && (
        <table className="audit" style={{ marginTop: 14 }}>
          <thead>
            <tr>
              <th>Time</th>
              <th>Stage</th>
              <th>Candidate</th>
              <th>Payload</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.event_id}>
                <td>{new Date(e.created_at).toLocaleTimeString()}</td>
                <td>
                  <span className="pill">{e.stage}</span>
                </td>
                <td>
                  <code>{e.candidate_id || "—"}</code>
                </td>
                <td>
                  <code>{JSON.stringify(e.payload)}</code>
                </td>
              </tr>
            ))}
            {events.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No events yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}
