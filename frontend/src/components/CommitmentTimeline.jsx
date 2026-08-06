/**
 * How a commitment moved during the meeting.
 *
 * The point of showing this rather than just the final state: "Rohit owns
 * this, due Thursday" reads as settled fact, when what actually happened
 * may have been Rohit taking it, handing it to Meera, and the date
 * slipping twice. A reviewer approving a task needs to see that history,
 * because a renegotiated commitment is the kind most likely to be wrong.
 *
 * Every node carries the verbatim line that caused it. Nothing here is
 * inferred narration — if there is no quote, the state change came from
 * a source that could not cite one, and that is worth noticing.
 */
const NEEDS_REAGREEMENT = new Set(["reassigned", "deadline_changed"]);

export default function CommitmentTimeline({ timeline, renegotiated }) {
  if (!timeline || timeline.length === 0) return null;

  return (
    <div>
      <strong style={{ fontSize: 13 }}>
        How this commitment moved{" "}
        <span className="muted">({timeline.length} change{timeline.length === 1 ? "" : "s"})</span>
      </strong>

      {renegotiated && (
        <p className="muted" style={{ margin: "6px 0 0" }}>
          The terms changed after someone had already agreed. Check the current owner and date
          against what was actually re-agreed at the end — not what was said first.
        </p>
      )}

      <ol className="timeline">
        {timeline.map((event, i) => (
          <li className={`s-${event.state}`} key={`${event.segment_id || "e"}-${i}`}>
            <div className="tl-head">
              <span className="tl-label">{event.label}</span>
              {event.actor && <span className="muted">{event.actor}</span>}
              <span className="muted">{event.at}</span>
              {event.owner_mention && <span className="pill">→ {event.owner_mention}</span>}
              {event.date_mention && <span className="pill">{event.date_mention}</span>}
              {NEEDS_REAGREEMENT.has(event.state) && (
                <span className="pill warn">needs fresh agreement</span>
              )}
            </div>
            {event.quote && <div className="tl-quote">“{event.quote}”</div>}
            {event.note && <div className="muted">{event.note}</div>}
          </li>
        ))}
      </ol>
    </div>
  );
}
