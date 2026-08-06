import { useState } from "react";
import CommitmentTimeline from "./CommitmentTimeline";
import FieldConfidence from "./FieldConfidence";

/**
 * One reviewable candidate.
 *
 * The reviewer must be able to see *why* something is or isn't allowed
 * before acting, so the gate reasons and the transcript evidence are
 * both first-class here rather than hidden behind a tooltip. The exact
 * payload that would be sent to GitHub is shown verbatim -- the brief
 * requires a person to see the exact payload before approval.
 */
const ALL_EFFECTS = [
  ["github_issue", "GitHub issue"],
  ["calendar_invite", "Calendar invite"],
  ["memory_index", "Cross-meeting memory"],
  ["notification", "Notify owner"],
];

export default function CandidateCard({ candidate, participants, reviewer, focused, onApprove, onReject, onEdit }) {
  const [open, setOpen] = useState(false);
  // Open by default when the terms changed mid-meeting — that is exactly
  // the case where the final state alone would mislead the reviewer.
  const [showTimeline, setShowTimeline] = useState(Boolean(candidate.was_renegotiated));
  const [effects, setEffects] = useState(["github_issue"]);
  const [confirmIt, setConfirmIt] = useState(false);
  const [results, setResults] = useState(null);
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
      setError({
        message: err.reasons?.length
          ? `${err.message} ${err.reasons.join("; ")}`
          : err.message,
        upstream: err.upstream && err.upstream !== err.message ? err.upstream : null,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className={`candidate ${eligible ? "eligible" : "blocked"} ${decided ? "done" : ""}`}
      // Keyboard focus needs a visible anchor, or J/K move an invisible cursor.
      style={focused ? { outline: "2px solid var(--accent)", outlineOffset: 2 } : undefined}
    >
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
        {candidate.was_renegotiated && <span className="pill warn">renegotiated</span>}
        {candidate.human_confirmed && <span className="pill ok">you confirmed this</span>}
        {candidate.review_status && <span className="pill accent">{candidate.review_status}</span>}
      </div>

      <FieldConfidence fields={candidate.field_confidence} />

      {candidate.contradiction_note && (
        <p className="muted">Contradiction: “{candidate.contradiction_note}”</p>
      )}

      {!eligible && (
        <div className="reasons">
          <strong>Needs your input before anything can be created:</strong>
          <ul>
            {candidate.gate.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="muted" style={{ margin: "8px 0 0" }}>
            It’s captured and kept either way. Use <strong>Edit</strong> to set the owner, the
            date, or to confirm it really was a commitment.
          </p>
        </div>
      )}

      {error && (
        <div className="error" style={{ marginTop: 12 }}>
          {error.message}
          {error.upstream && (
            <div className="muted" style={{ marginTop: 6, wordBreak: "break-word" }}>
              {error.upstream}
            </div>
          )}
        </div>
      )}

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
        {candidate.timeline?.length > 1 && (
          <button className="ghost" onClick={() => setShowTimeline((v) => !v)}>
            {showTimeline ? "Hide history" : `History (${candidate.timeline.length})`}
          </button>
        )}
        <button className="ghost" onClick={() => setEditing((v) => !v)} disabled={busy}>
          {editing ? "Cancel edit" : "Edit"}
        </button>
        <button
          className="primary"
          disabled={busy || !eligible || decided || effects.length === 0}
          title={eligible ? "" : "Blocked by the safety gate"}
          onClick={() =>
            run(async () => {
              setResults(await onApprove(candidate.candidate_id, effects));
            })
          }
        >
          Approve &amp; run {effects.length} action{effects.length === 1 ? "" : "s"}
        </button>
        <button
          className="danger"
          disabled={busy || decided}
          onClick={() => run(() => onReject(candidate.candidate_id))}
        >
          Reject
        </button>
      </div>

      {!decided && eligible && (
        <div className="drawer">
          <strong style={{ fontSize: 13 }}>Actions to take on approval</strong>
          <p className="muted" style={{ margin: "4px 0 8px" }}>
            Each is gated identically. Approving never fans out to more systems than you tick.
          </p>
          <div className="meta">
            {ALL_EFFECTS.map(([value, label]) => (
              <label
                key={value}
                className="pill"
                style={{ cursor: "pointer", gap: 6 }}
              >
                <input
                  type="checkbox"
                  style={{ width: "auto", margin: 0 }}
                  checked={effects.includes(value)}
                  onChange={(e) =>
                    setEffects((prev) =>
                      e.target.checked ? [...prev, value] : prev.filter((x) => x !== value)
                    )
                  }
                />
                {label}
              </label>
            ))}
          </div>
        </div>
      )}

      {showTimeline && candidate.timeline?.length > 0 && (
        <div className="drawer">
          <CommitmentTimeline
            timeline={candidate.timeline}
            renegotiated={candidate.was_renegotiated}
          />
        </div>
      )}

      {results?.effects?.length > 0 && (
        <div className="drawer">
          <strong style={{ fontSize: 13 }}>Result</strong>
          <div className="meta" style={{ marginTop: 6 }}>
            {results.effects.map((e) => (
              <span
                key={e.effect}
                className={`pill ${
                  e.status === "created"
                    ? "ok"
                    : e.status === "duplicate_suppressed"
                    ? "accent"
                    : e.status === "failed"
                    ? "bad"
                    : "warn"
                }`}
                title={e.error || ""}
              >
                {e.effect}: {e.status.replace("_", " ")}
              </span>
            ))}
          </div>
        </div>
      )}

      {editing && (
        <div className="drawer">
          <p className="muted">
            Edits change the item itself, so the safety gate re-evaluates the corrected values.
          </p>
          {candidate.classification !== "confirmed" && (
            <div
              className="field"
              style={{
                padding: 10,
                background: "var(--bg)",
                borderRadius: 8,
                marginBottom: 14,
              }}
            >
              <label style={{ display: "flex", gap: 9, cursor: "pointer", marginBottom: 0 }}>
                <input
                  type="checkbox"
                  style={{ width: "auto", marginTop: 3 }}
                  checked={confirmIt}
                  onChange={(e) => setConfirmIt(e.target.checked)}
                />
                <span style={{ color: "var(--text)", fontSize: 13 }}>
                  <strong>This really was a commitment.</strong> The model read it as “
                  {candidate.classification}”. If you were in the room and know someone took it,
                  say so — it’s recorded as your decision in the audit log.
                </span>
              </label>
            </div>
          )}

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
                if (confirmIt) changes.classification = "confirmed";
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
