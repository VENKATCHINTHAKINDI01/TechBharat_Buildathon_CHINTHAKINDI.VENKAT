import { useEffect, useState } from "react";
import { deleteMeeting, listMeetings } from "../api/client";
import { EmptyState, ErrorState, Loading } from "../ui/states";

/**
 * Every meeting this workspace has seen, newest first.
 *
 * Counts come pre-aggregated from the server — rendering a list of fifty
 * meetings by fetching each one's detail would be fifty round trips.
 */
export default function MeetingHistory({ onOpenReview, onOpenReport }) {
  const [meetings, setMeetings] = useState(null);
  const [error, setError] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);

  const load = () =>
    listMeetings()
      .then(setMeetings)
      .catch((err) => setError(err.message));

  useEffect(() => {
    load();
  }, []);

  async function handleDelete(meetingId) {
    setDeletingId(meetingId);
    try {
      await deleteMeeting(meetingId);
      setConfirmId(null);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeletingId(null);
    }
  }

  if (error) return <ErrorState title="Could not load meetings" detail={error} />;
  if (!meetings) return <Loading label="Loading meetings" card lines={3} />;

  if (meetings.length === 0) {
    return (
      <section className="panel">
        <h2>Past meetings</h2>
        <EmptyState icon="⧉" title="No meetings yet">
          Upload a transcript or a recording, or run a live meeting. Each one appears here with
          its report and everything that was actioned.
        </EmptyState>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>Past meetings ({meetings.length})</h2>
      {meetings.map((m) => {
        const pending = Math.max(0, (m.action_items || 0) - (m.reviewed || 0));
        const isDeleting = deletingId === m.meeting_id;
        const isConfirming = confirmId === m.meeting_id;

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

              {/* Inline delete confirmation */}
              {isConfirming && (
                <div
                  style={{
                    marginTop: 10,
                    padding: "10px 14px",
                    background: "rgba(239,68,68,0.08)",
                    borderRadius: 8,
                    border: "1px solid rgba(239,68,68,0.3)",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    flexWrap: "wrap",
                  }}
                >
                  <span style={{ fontSize: 13, color: "var(--text)" }}>
                    ⚠️ Delete <strong>{m.title}</strong>? All local data will be removed.
                    GitHub issues already created are <strong>preserved</strong>.
                  </span>
                  <button
                    className="danger"
                    style={{ padding: "4px 14px", fontSize: 13 }}
                    disabled={isDeleting}
                    onClick={() => handleDelete(m.meeting_id)}
                  >
                    {isDeleting ? "Deleting…" : "Yes, delete"}
                  </button>
                  <button
                    className="ghost"
                    style={{ padding: "4px 14px", fontSize: 13 }}
                    onClick={() => setConfirmId(null)}
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <button className="ghost" onClick={() => onOpenReport(m.meeting_id)}>
                Report
              </button>
              <button className="primary" onClick={() => onOpenReview(m.meeting_id)}>
                {pending > 0 ? "Review & approve" : "Open"}
              </button>
              {!isConfirming && (
                <button
                  className="danger"
                  style={{ padding: "6px 12px", fontSize: 13 }}
                  title="Delete this meeting and all its data"
                  onClick={() => setConfirmId(m.meeting_id)}
                >
                  Delete
                </button>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
