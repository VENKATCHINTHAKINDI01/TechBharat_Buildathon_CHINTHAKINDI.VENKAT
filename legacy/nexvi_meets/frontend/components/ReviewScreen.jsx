import { useEffect, useState, useCallback } from "react";
import ActionItemCard from "./ActionItemCard";
import { getMeetingForReview, approveActionItem, rejectActionItem, editActionItem } from "../services/api";

export default function ReviewScreen({ meetingId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const result = await getMeetingForReview(meetingId);
      setData(result);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load meeting");
    }
  }, [meetingId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleApprove(dedupeHash) {
    await approveActionItem(dedupeHash);
    refresh();
  }

  async function handleReject(dedupeHash) {
    await rejectActionItem(dedupeHash);
    refresh();
  }

  async function handleEdit(dedupeHash, changes) {
    await editActionItem(dedupeHash, changes);
    refresh();
  }

  if (error) return <div style={{ color: "#c0392b" }}>{error}</div>;
  if (!data) return <div>Loading meeting…</div>;

  const { meeting, structured_record, action_items } = data;

  return (
    <div>
      <h2>{meeting.title}</h2>
      {structured_record && (
        <div style={{ background: "#f7f7f5", padding: 12, borderRadius: 6, marginBottom: 16 }}>
          <p>{structured_record.executive_summary}</p>
          {structured_record.decisions?.length > 0 && (
            <>
              <strong>Decisions</strong>
              <ul>{structured_record.decisions.map((d, i) => <li key={i}>{d}</li>)}</ul>
            </>
          )}
          {structured_record.risks?.length > 0 && (
            <>
              <strong>Risks</strong>
              <ul>{structured_record.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </>
          )}
        </div>
      )}

      <h3>Action items ({action_items.length})</h3>
      {action_items.map((item) => (
        <ActionItemCard
          key={item.dedupe_hash}
          item={item}
          onApprove={handleApprove}
          onReject={handleReject}
          onEdit={handleEdit}
        />
      ))}
    </div>
  );
}