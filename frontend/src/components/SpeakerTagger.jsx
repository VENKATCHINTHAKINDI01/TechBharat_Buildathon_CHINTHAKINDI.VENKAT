import { useEffect, useMemo, useState } from "react";
import { assignSpeakers, getTranscript } from "../api/client";
import { useToast } from "../ui/toast";
import { Loading } from "../ui/states";

/**
 * Saying who spoke in an uploaded recording.
 *
 * Speech-to-text returns words, not speakers, so a transcribed recording
 * arrives entirely as "Unknown speaker" — and unattributed speech cannot
 * own an action item, so the whole meeting is gate-blocked. This panel is
 * the one thing standing between that and an approvable review queue.
 *
 * Two granularities, because both are needed:
 *
 * - **Relabel a whole speaker.** One click for "everything marked Unknown
 *   was Arjun". On a 45-minute recording, per-line tagging would be
 *   unusable, so this is the primary control.
 * - **Per-line assignment.** For the lines the bulk action got wrong.
 *
 * Re-analysis runs automatically afterwards: attribution only matters
 * because it changes what the extractor can resolve, so making the user
 * press a second button would just be a way to forget.
 */
export default function SpeakerTagger({ meetingId, participants, onReanalysed }) {
  const [segments, setSegments] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState({});   // segment_id -> participant_id
  const [expanded, setExpanded] = useState(false);
  const toast = useToast();

  useEffect(() => {
    let cancelled = false;
    getTranscript(meetingId)
      .then((data) => !cancelled && setSegments(data.segments || []))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [meetingId]);

  const unnamed = useMemo(() => {
    if (!segments) return [];
    const known = new Set(participants.map((p) => p.name));
    return [...new Set(segments.map((s) => s.speaker))].filter((s) => !known.has(s));
  }, [segments, participants]);

  if (error) return <div className="error">{error}</div>;
  if (!segments) return <Loading label="Loading transcript" lines={2} />;

  // Everything is already attributed to a real participant: nothing to do.
  if (unnamed.length === 0) return null;

  const untagged = segments.filter((s) => unnamed.includes(s.speaker));

  async function run(payload, description) {
    setBusy(true);
    try {
      const result = await assignSpeakers(meetingId, payload);
      const fresh = await getTranscript(meetingId);
      setSegments(fresh.segments || []);
      setPending({});

      if (result.warnings?.length) {
        toast.warn(description, result.warnings[0]);
      } else if (result.reanalysed) {
        toast.success(
          description,
          `${result.segments_updated} line(s) attributed · ${result.candidates} commitment(s), ` +
            `${result.eligible} now ready to approve.`
        );
      } else {
        toast.success(description, `${result.segments_updated} line(s) attributed.`);
      }
      onReanalysed?.();
    } catch (err) {
      toast.error("Could not assign speakers", err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Who was speaking?</h2>

      <div className="notice">
        <strong>
          {untagged.length} line(s) have no speaker, so nothing from them can be approved.
        </strong>{" "}
        A recording carries words, not names — Naina will not guess who spoke, because a guessed
        owner is precisely what the safety gate exists to stop. Tell her, and she re-reads the
        meeting with the names in place.
      </div>

      {unnamed.map((label) => (
        <div className="field" key={label} style={{ marginBottom: 12 }}>
          <label>
            Everything currently marked “{label}”{" "}
            <span className="muted">
              ({segments.filter((s) => s.speaker === label).length} lines)
            </span>
          </label>
          <div className="meta">
            {participants.map((p) => (
              <button
                key={p.participant_id}
                disabled={busy}
                onClick={() =>
                  run(
                    { relabel: { [label]: p.participant_id }, reanalyze: true },
                    `All of “${label}” is ${p.name}`
                  )
                }
              >
                {p.name}
              </button>
            ))}
          </div>
        </div>
      ))}

      <div className="actions">
        <button className="ghost" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Hide line-by-line" : `Tag line by line (${untagged.length})`}
        </button>
      </div>

      {expanded && (
        <div className="drawer" style={{ maxHeight: 380, overflowY: "auto" }}>
          {untagged.map((segment) => (
            <blockquote className="evidence" key={segment.segment_id}>
              <div>{segment.text}</div>
              <div className="meta" style={{ marginTop: 8 }}>
                <span className="muted">
                  {Math.round((segment.start_ms || 0) / 1000)}s
                </span>
                {participants.map((p) => (
                  <button
                    key={p.participant_id}
                    className={
                      pending[segment.segment_id] === p.participant_id ? "primary tiny" : "tiny"
                    }
                    disabled={busy}
                    onClick={() =>
                      setPending((current) => ({
                        ...current,
                        [segment.segment_id]: p.participant_id,
                      }))
                    }
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            </blockquote>
          ))}

          <div className="actions">
            <button
              className="primary"
              disabled={busy || Object.keys(pending).length === 0}
              onClick={() =>
                run(
                  { assignments: pending, reanalyze: true },
                  `${Object.keys(pending).length} line(s) attributed`
                )
              }
            >
              Apply {Object.keys(pending).length} assignment(s) and re-analyse
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
