import { useState } from "react";

/**
 * One reviewable candidate.
 *
 * The reviewer must be able to see *why* something is or isn't allowed
 * before acting, so the gate reasons and the transcript evidence are
 * both first-class here rather than hidden behind a tooltip. The exact
 * payload that would be sent to GitHub is shown verbatim -- the brief
 * requires a person to see the exact payload before approval.
 */
export default function CandidateCard({ candidate, participants, reviewer, onApprove, onReject, onEdit }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [ownerId, setOwnerId] = useState(candidate.owner_participant_id || "");
  const [dueDate, setDueDate] = useState(candidate.due_date || "");

  const decided = Boolean(candidate.review_status);
  const eligible = candidate.gate.eligible;

  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err.reasons?.length ? `${err.message} ${err.reasons.join("; ")}` : err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className={`candidate ${eligible ? "eligible" : "blocked"} ${decided ? "done" : ""}`}>
      <h3>{candidate.raw_text}</h3>

      <div className="meta">
        <span className="pill">{candidate.kind.replace("_", " ")}</span>
        <span className={`pill ${candidate.classification === "confirmed" ? "ok" : "warn"}`}>
          {candidate.classification}
        </span>
        <span className="pill">{candidate.owner_name || "no owner"}</span>
        <span className="pill">{candidate.due_date || "no date"}</span>
        <span className="pill">{candidate.priority}</span>
        <span className="pill">conf {candidate.confidence.toFixed(2)}</span>
        <span className={`pill ${eligible ? "ok" : "bad"}`}>
          {eligible ? "gate: eligible" : "gate: blocked"}
        </span>
        {candidate.review_status && <span className="pill accent">{candidate.review_status}</span>}
      </div>

      {candidate.contradiction_note && (
        <p className="muted">Contradiction: “{candidate.contradiction_note}”</p>
      )}

      {!eligible && (
        <div className="reasons">
          <strong>Blocked by the safety gate:</strong>
          <ul>
            {candidate.gate.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}

      {candidate.issue_url && (
        <p style={{ marginTop: 12 }}>
          Created:{" "}
          <a href={candidate.issue_url} target="_blank" rel="noreferrer">
            {candidate.issue_url}
          </a>
        </p>
      )}

      <div className="actions">
        <button className="ghost" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide evidence" : `Evidence (${candidate.evidence.length})`}
        </button>
        <button className="ghost" onClick={() => setEditing((v) => !v)} disabled={busy}>
          {editing ? "Cancel edit" : "Edit"}
        </button>
        <button
          className="primary"
          disabled={busy || !eligible || decided}
          title={eligible ? "" : "Blocked by the safety gate"}
          onClick={() => run(() => onApprove(candidate.candidate_id))}
        >
          Approve &amp; create issue
        </button>
        <button
          className="danger"
          disabled={busy || decided}
          onClick={() => run(() => onReject(candidate.candidate_id))}
        >
          Reject
        </button>
      </div>

      {editing && (
        <div className="drawer">
          <p className="muted">
            Edits change the item itself, so the safety gate re-evaluates the corrected values.
          </p>
          <div className="row">
            <div className="field">
              <label htmlFor={`owner-${candidate.candidate_id}`}>Owner</label>
              <select
                id={`owner-${candidate.candidate_id}`}
                value={ownerId}
                onChange={(e) => setOwnerId(e.target.value)}
              >
                <option value="">— unresolved —</option>
                {participants.map((p) => (
                  <option key={p.participant_id} value={p.participant_id}>
                    {p.name}
                    {p.aliases?.length ? ` (${p.aliases.join(", ")})` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor={`due-${candidate.candidate_id}`}>Due date</label>
              <input
                id={`due-${candidate.candidate_id}`}
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
              />
            </div>
          </div>
          <button
            disabled={busy}
            onClick={() =>
              run(async () => {
                const changes = {};
                if (ownerId) changes.owner_participant_id = ownerId;
                if (dueDate) changes.due_date = dueDate;
                await onEdit(candidate.candidate_id, changes);
                setEditing(false);
              })
            }
          >
            Save changes
          </button>
        </div>
      )}

      {open && (
        <div className="drawer">
          <strong style={{ fontSize: 13 }}>Transcript evidence</strong>
          {candidate.evidence.length === 0 && <p className="muted">No supporting quotes.</p>}
          {candidate.evidence.map((q, i) => (
            <blockquote className="evidence" key={`${q.segment_id}-${i}`}>
              {q.quote}
              <cite>{q.segment_id}</cite>
            </blockquote>
          ))}

          {candidate.proposed_payload && (
            <>
              <strong style={{ fontSize: 13 }}>Exact payload that will be sent</strong>
              <pre className="payload">
{JSON.stringify(candidate.proposed_payload, null, 2)}
              </pre>
            </>
          )}
        </div>
      )}
    </article>
  );
}
