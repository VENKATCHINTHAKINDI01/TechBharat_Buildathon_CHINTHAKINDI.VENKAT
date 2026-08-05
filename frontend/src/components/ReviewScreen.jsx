import { useCallback, useEffect, useState } from "react";
import { approveCandidate, editCandidate, getMeeting, rejectCandidate } from "../api/client";
import CandidateCard from "./CandidateCard";
import MeetingRecord from "./MeetingRecord";
import AuditLog from "./AuditLog";

export default function ReviewScreen({ meetingId, uploadSummary, onBack }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [reviewer, setReviewer] = useState("demo_reviewer");
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    try {
      setDetail(await getMeeting(meetingId));
    } catch (err) {
      setError(err.message);
    }
  }, [meetingId]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = async () => {
    await load();
    setRefreshKey((k) => k + 1);
  };

  if (error) return <div className="error">{error}</div>;
  if (!detail) return <p className="muted">Loading meeting…</p>;

  const participants = detail.participants || [];
  const eligible = detail.candidates.filter((c) => c.gate.eligible).length;
  const blocked = detail.candidates.length - eligible;

  return (
    <>
      <div className="actions" style={{ marginBottom: 16 }}>
        <button className="ghost" onClick={onBack}>
          ← Upload another
        </button>
        <span className="pill">{detail.title}</span>
        <span className="pill">{detail.meeting_date}</span>
        {uploadSummary && (
          <span className="pill accent">extractor: {uploadSummary.extractor_used}</span>
        )}
      </div>

      {uploadSummary?.fallback_reason && (
        <div className="notice">
          Primary extractor unavailable, used the deterministic fallback:{" "}
          {uploadSummary.fallback_reason}
        </div>
      )}
      {uploadSummary?.warnings?.map((w) => (
        <div className="notice" key={w}>
          {w}
        </div>
      ))}

      <MeetingRecord record={detail.record} />

      <section className="panel">
        <h2>
          Review queue — {eligible} eligible, {blocked} blocked
        </h2>
        <div className="field" style={{ maxWidth: 260 }}>
          <label htmlFor="reviewer">Reviewer (recorded in the audit log)</label>
          <input id="reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </div>

        {detail.candidates.length === 0 && (
          <p className="muted">No candidates were extracted from this transcript.</p>
        )}

        {detail.candidates.map((candidate) => (
          <CandidateCard
            key={candidate.candidate_id}
            candidate={candidate}
            participants={participants}
            reviewer={reviewer}
            onApprove={async (id) => {
              await approveCandidate(id, reviewer);
              await refresh();
            }}
            onReject={async (id) => {
              await rejectCandidate(id, reviewer, "rejected in review");
              await refresh();
            }}
            onEdit={async (id, changes) => {
              await editCandidate(id, reviewer, changes);
              await refresh();
            }}
          />
        ))}
      </section>

      <AuditLog meetingId={meetingId} refreshKey={refreshKey} />
    </>
  );
}
