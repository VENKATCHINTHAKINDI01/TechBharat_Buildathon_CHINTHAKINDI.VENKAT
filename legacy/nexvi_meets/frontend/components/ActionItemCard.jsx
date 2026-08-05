import { useState } from "react";

const STATUS_COLORS = {
  pending_review: "#e0a000",
  approved: "#1a8a4a",
  rejected: "#c0392b",
  edited: "#2b6cc0",
};

export default function ActionItemCard({ item, onApprove, onReject, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(item.text);
  const [draftOwner, setDraftOwner] = useState(item.owner_raw);

  const needsOwnerReview = !item.owner_resolved;
  const lowConfidence = item.confidence_score < 0.6;

  function saveEdit() {
    const changes = {};
    if (draftText !== item.text) changes.text = draftText;
    if (draftOwner !== item.owner_raw) changes.owner_raw = draftOwner;
    if (Object.keys(changes).length > 0) onEdit(item.dedupe_hash, changes);
    setEditing(false);
  }

  return (
    <div
      style={{
        border: "1px solid #ddd",
        borderLeft: `4px solid ${STATUS_COLORS[item.status] || "#999"}`,
        borderRadius: 6,
        padding: 12,
        marginBottom: 10,
      }}
    >
      {editing ? (
        <>
          <input
            style={{ width: "100%", marginBottom: 6 }}
            value={draftText}
            onChange={(e) => setDraftText(e.target.value)}
          />
          <input
            style={{ width: "100%", marginBottom: 6 }}
            value={draftOwner}
            onChange={(e) => setDraftOwner(e.target.value)}
            placeholder="owner name"
          />
          <button onClick={saveEdit}>Save</button>
          <button onClick={() => setEditing(false)}>Cancel</button>
        </>
      ) : (
        <>
          <div style={{ fontWeight: 600 }}>{item.text}</div>
          <div style={{ fontSize: 13, color: "#555", marginTop: 4 }}>
            Owner: {item.owner_resolved ? item.owner_resolved.name : item.owner_raw}{" "}
            {needsOwnerReview && (
              <span style={{ color: "#c0392b" }}>&#9888; unresolved — needs manual assignment</span>
            )}
          </div>
          <div style={{ fontSize: 13, color: "#555" }}>
            Due: {item.due_date_resolved ? new Date(item.due_date_resolved).toLocaleDateString() : "not set"}
            {" · "}Priority: {item.priority}
            {" · "}Confidence: {(item.confidence_score * 100).toFixed(0)}%
            {lowConfidence && <span style={{ color: "#e0a000" }}> (low)</span>}
          </div>
          <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>Status: {item.status}</div>
          {item.calendar_event_id && (
            <div style={{ fontSize: 12, color: "#1a8a4a", marginTop: 2 }}>
              &#10003; Calendar invite sent (event {item.calendar_event_id})
            </div>
          )}
          {item.status === "pending_review" && (
            <div style={{ marginTop: 8 }}>
              <button onClick={() => onApprove(item.dedupe_hash)}>Approve</button>
              <button onClick={() => setEditing(true)}>Edit</button>
              <button onClick={() => onReject(item.dedupe_hash)}>Reject</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}