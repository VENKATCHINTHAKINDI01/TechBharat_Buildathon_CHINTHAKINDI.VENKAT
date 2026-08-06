import { useCallback, useEffect, useMemo, useState } from "react";
import { approveCandidate, editCandidate, getMeeting, rejectCandidate } from "../api/client";
import CandidateCard from "./CandidateCard";
import MeetingRecord from "./MeetingRecord";
import AuditLog from "./AuditLog";
import AgentTrace from "./AgentTrace";
import SpeakerTagger from "./SpeakerTagger";
import { useToast } from "../ui/toast";
import { Loading, ErrorState } from "../ui/states";
import { useShortcuts } from "../ui/CommandPalette";

/**
 * An empty review queue, explained.
 *
 * "No candidates were extracted from this transcript" was the only thing
 * shown after a live meeting that captured plenty of speech, and it is
 * ambiguous between three completely different situations: a meeting
 * with no commitments in it, an LLM that failed and fell back to the
 * weak pattern extractor, and an LLM that answered but quoted words
 * nobody said. Each needs a different fix, so each gets a different
 * message.
 */
function EmptyQueue({ extraction }) {
  if (!extraction) {
    return <p className="muted">No candidates were extracted from this transcript.</p>;
  }

  const { fallback_reason, extractor, segments, evidence_dropped_items, warnings } = extraction;

  if (fallback_reason) {
    return (
      <div className="error">
        <strong>The AI extractor failed, so nothing could be analysed properly.</strong>
        <p style={{ margin: "8px 0 0", fontSize: 13 }}>
          Naina fell back to the pattern-based extractor, which only recognises a few
          scripted phrasings and finds very little in natural speech.
        </p>
        <p className="muted" style={{ marginTop: 8, wordBreak: "break-word" }}>
          Reason: {fallback_reason}
        </p>
        <p className="muted" style={{ marginTop: 8 }}>
          Most likely: an expired or invalid <code>GROQ_API_KEY</code>, or a{" "}
          <code>GROQ_MODEL</code> that has been retired. Run{" "}
          <code>python ../scripts/live_check.py</code> to confirm which.
        </p>
      </div>
    );
  }

  if (evidence_dropped_items > 0) {
    return (
      <div className="notice">
        <strong>
          {evidence_dropped_items} item{evidence_dropped_items === 1 ? " was" : "s were"} found
          but could not be shown.
        </strong>
        <p style={{ margin: "8px 0 0", fontSize: 13 }}>
          The AI quoted words that do not appear in the transcript, so those items have no
          usable evidence. Nexvi.Meets will not show a commitment it cannot back with the
          speaker&rsquo;s actual words — see the audit log for what was dropped.
        </p>
      </div>
    );
  }

  return (
    <div className="notice">
      <strong>No commitments were found in this meeting.</strong>
      <p style={{ margin: "8px 0 0", fontSize: 13 }}>
        {segments > 0
          ? `${segments} transcript segment(s) were analysed by the '${extractor || "unknown"}' extractor.`
          : "Nothing was captured to analyse."}{" "}
        That is a normal outcome for a discussion where nobody committed to anything.
      </p>
      {warnings?.length > 0 && (
        <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12 }}>
          {warnings.map((w) => (
            <li key={w} className="muted">{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ReviewScreen({ meetingId, uploadSummary, onBack, onOpenReport }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [reviewer, setReviewer] = useState("demo_reviewer");
  const [refreshKey, setRefreshKey] = useState(0);
  const [focused, setFocused] = useState(0);
  const toast = useToast();

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

  const candidates = detail?.candidates || [];

  // J/K move a highlight through the queue; A and R act on it. Approving
  // twenty items by mouse is the slowest part of a demo.
  useShortcuts(
    useMemo(
      () => ({
        j: () => setFocused((i) => Math.min(i + 1, Math.max(candidates.length - 1, 0))),
        k: () => setFocused((i) => Math.max(i - 1, 0)),
        a: async () => {
          const target = candidates[focused];
          if (!target || !target.gate.eligible || target.review_status) return;
          try {
            await approveCandidate(target.candidate_id, reviewer, ["github_issue"]);
            toast.success("Approved", target.raw_text.slice(0, 70));
            await refresh();
          } catch (err) {
            toast.error("Approval failed", err.message);
          }
        },
        r: async () => {
          const target = candidates[focused];
          if (!target || target.review_status) return;
          try {
            await rejectCandidate(target.candidate_id, reviewer, "rejected in review");
            toast.info("Rejected", target.raw_text.slice(0, 70));
            await refresh();
          } catch (err) {
            toast.error("Rejection failed", err.message);
          }
        },
      }),
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [candidates, focused, reviewer, toast]
    )
  );

  if (error) {
    return <ErrorState title="Could not load this meeting" detail={error} onRetry={load} />;
  }
  if (!detail) return <Loading label="Loading meeting" card lines={3} />;

  const participants = detail.participants || [];
  const eligible = candidates.filter((c) => c.gate.eligible).length;
  const blocked = candidates.length - eligible;

  return (
    <>
      <div className="actions" style={{ marginBottom: 16 }}>
        <button className="ghost" onClick={onBack}>
          ← Back
        </button>
        {onOpenReport && (
          <button className="ghost" onClick={onOpenReport}>
            View report
          </button>
        )}
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

      {/* Only renders when speech is still unattributed, which is the
          case for an uploaded recording and never for a parsed
          transcript. */}
      <SpeakerTagger
        meetingId={meetingId}
        participants={participants}
        onReanalysed={refresh}
      />

      <MeetingRecord record={detail.record} />

      <section className="panel">
        <h2>
          Review queue — {eligible} eligible, {blocked} blocked
        </h2>
        <div className="field" style={{ maxWidth: 260 }}>
          <label htmlFor="reviewer">Reviewer (recorded in the audit log)</label>
          <input id="reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </div>

        {candidates.length === 0 && <EmptyQueue extraction={detail.extraction} />}

        <div className="stagger">
        {candidates.map((candidate, index) => (
          <CandidateCard
            key={candidate.candidate_id}
            focused={index === focused}
            candidate={candidate}
            participants={participants}
            reviewer={reviewer}
            onApprove={async (id, effects) => {
              const result = await approveCandidate(id, reviewer, effects);
              const failed = (result.effects || []).filter((e) => e.status === "failed");
              if (failed.length) {
                toast.warn(
                  `Approved, but ${failed.length} action failed`,
                  failed[0].error || failed[0].effect
                );
              } else {
                toast.success("Approved", candidate.raw_text.slice(0, 70));
              }
              await refresh();
              return result;
            }}
            onReject={async (id) => {
              await rejectCandidate(id, reviewer, "rejected in review");
              toast.info("Rejected", candidate.raw_text.slice(0, 70));
              await refresh();
            }}
            onEdit={async (id, changes) => {
              await editCandidate(id, reviewer, changes);
              toast.success("Saved", "The safety gate re-evaluated the corrected values.");
              await refresh();
            }}
          />
        ))}
        </div>

        {candidates.length > 1 && (
          <p className="muted" style={{ marginTop: 12 }}>
            <kbd>J</kbd>/<kbd>K</kbd> move · <kbd>A</kbd> approve · <kbd>R</kbd> reject ·{" "}
            <kbd>⌘K</kbd> palette
          </p>
        )}
      </section>

      <AgentTrace meetingId={meetingId} />
      <AuditLog meetingId={meetingId} refreshKey={refreshKey} />
    </>
  );
}
