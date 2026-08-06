import { useEffect, useState } from "react";
import { getReport, reportMarkdownUrl } from "../api/client";

/**
 * The end-of-meeting report.
 *
 * Regenerated server-side on every open, so a report read a week later
 * shows work approved since the meeting rather than a frozen snapshot.
 */
export default function ReportView({ meetingId, onBack, onOpenReview }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setReport(null);
    getReport(meetingId)
      .then(setReport)
      .catch((err) => setError(err.message));
  }, [meetingId]);

  if (error) return <div className="error">{error}</div>;
  if (!report) return <p className="muted">Building report…</p>;

  const statusOf = (item) =>
    item.actions?.some((a) => ["created", "duplicate_suppressed"].includes(a.status))
      ? { label: "actioned", cls: "ok" }
      : !item.gate_eligible
      ? { label: "blocked", cls: "bad" }
      : item.review_status
      ? { label: item.review_status, cls: "accent" }
      : { label: "awaiting approval", cls: "warn" };

  const actioned = report.action_items.filter((i) => statusOf(i).label === "actioned").length;
  const blocked = report.action_items.filter((i) => !i.gate_eligible).length;
  const pending = report.action_items.length - actioned - blocked;

  const List = ({ title, items }) =>
    items.length === 0 ? null : (
      <div className="report-section">
        <h3>{title}</h3>
        {items.map((i) => (
          <div className="candidate" key={i.candidate_id} style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 14 }}>{i.text}</div>
            {i.classification !== "confirmed" && (
              <span className="pill warn" style={{ marginTop: 6 }}>
                {i.classification}
              </span>
            )}
          </div>
        ))}
      </div>
    );

  return (
    <>
      <div className="actions" style={{ marginBottom: 16 }}>
        <button className="ghost" onClick={onBack}>
          ← Back
        </button>
        <span className="pill">{report.meeting_id}</span>
        <span className="pill">{report.meeting_date}</span>
        <span className="pill accent">{report.source}</span>
        <a
          className="pill"
          href={reportMarkdownUrl(meetingId)}
          target="_blank"
          rel="noreferrer"
          style={{ textDecoration: "none" }}
        >
          ↓ markdown
        </a>
        <button className="primary" onClick={() => onOpenReview(meetingId)}>
          Review &amp; approve
        </button>
      </div>

      <section className="panel">
        <h2>{report.title || "Meeting report"}</h2>
        {report.executive_summary && <p className="summary">{report.executive_summary}</p>}

        <div className="buckets">
          <div className="bucket">
            <div className="n" style={{ color: "var(--ok)" }}>{actioned}</div>
            <div className="k">actioned</div>
          </div>
          <div className="bucket">
            <div className="n" style={{ color: "var(--warn)" }}>{pending}</div>
            <div className="k">awaiting approval</div>
          </div>
          <div className="bucket">
            <div className="n" style={{ color: "var(--bad)" }}>{blocked}</div>
            <div className="k">blocked by gate</div>
          </div>
          <div className="bucket">
            <div className="n">{report.decisions.length}</div>
            <div className="k">decisions</div>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Action items</h2>
        {report.action_items.length === 0 && (
          <p className="muted">No action items were extracted from this meeting.</p>
        )}
        {report.action_items.map((item) => {
          const status = statusOf(item);
          return (
            <div
              className={`candidate ${item.gate_eligible ? "eligible" : "blocked"}`}
              key={item.candidate_id}
            >
              <h3>{item.text}</h3>
              <div className="meta">
                <span className={`pill ${status.cls}`}>{status.label}</span>
                <span className="pill">{item.owner_name || "no owner"}</span>
                <span className="pill">{item.due_date || "no date"}</span>
                <span className="pill">{item.priority}</span>
                <span className="pill">conf {item.confidence?.toFixed(2)}</span>
              </div>

              {!item.gate_eligible && item.gate_reasons?.length > 0 && (
                <div className="reasons">
                  <strong>Blocked by the safety gate:</strong>
                  <ul>
                    {item.gate_reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}

              {item.actions?.length > 0 && (
                <div className="meta" style={{ marginTop: 10, marginBottom: 0 }}>
                  {item.actions.map((a, idx) => (
                    <span
                      key={`${a.effect}-${idx}`}
                      className={`pill ${a.status === "created" ? "ok" : a.status === "failed" ? "bad" : "accent"}`}
                      title={a.error || a.summary}
                    >
                      {a.url ? (
                        <a href={a.url} target="_blank" rel="noreferrer">
                          {a.effect}: {a.status}
                        </a>
                      ) : (
                        `${a.effect}: ${a.status}`
                      )}
                    </span>
                  ))}
                </div>
              )}

              {item.evidence?.length > 0 && (
                <div className="drawer">
                  {item.evidence.slice(0, 2).map((q, i) => (
                    <blockquote className="evidence" key={i}>
                      {q.quote}
                      <cite>{q.segment_id}</cite>
                    </blockquote>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </section>

      {(report.decisions.length > 0 ||
        report.risks_blockers.length > 0 ||
        report.open_questions.length > 0) && (
        <section className="panel">
          <h2>Also discussed</h2>
          <List title="Decisions" items={report.decisions} />
          <List title="Risks and blockers" items={report.risks_blockers} />
          <List title="Open questions" items={report.open_questions} />
        </section>
      )}

      <section className="panel">
        <h2>Actions taken</h2>
        {report.actions_taken.length === 0 ? (
          <p className="muted">Nothing was created. No item was approved.</p>
        ) : (
          <table className="audit">
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>Status</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {report.actions_taken.map((a, i) => (
                <tr key={`${a.effect}-${i}`}>
                  <td>{a.at ? new Date(a.at).toLocaleTimeString() : "—"}</td>
                  <td>
                    <span className="pill">{a.effect}</span>
                  </td>
                  <td>
                    <span
                      className={`pill ${a.status === "created" ? "ok" : a.status === "failed" ? "bad" : "warn"}`}
                    >
                      {a.status}
                    </span>
                  </td>
                  <td>
                    {a.url ? (
                      <a href={a.url} target="_blank" rel="noreferrer">
                        {a.summary || a.url}
                      </a>
                    ) : (
                      a.summary
                    )}
                    {a.error && <div className="muted">{a.error}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {report.speaker_stats?.length > 0 && (
        <section className="panel">
          <h2>Talk time</h2>
          <table className="audit">
            <thead>
              <tr>
                <th>Speaker</th>
                <th>Segments</th>
                <th>Words</th>
                <th>Share</th>
              </tr>
            </thead>
            <tbody>
              {report.speaker_stats.map((s) => (
                <tr key={s.speaker}>
                  <td>{s.speaker}</td>
                  <td>{s.segments}</td>
                  <td>{s.words}</td>
                  <td>{Math.round(s.share * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {report.unattributed_segments > 0 && (
            <p className="muted" style={{ marginTop: 10 }}>
              {report.unattributed_segments} segment(s) were never attributed to a named speaker,
              so nothing said in them can own an action item.
            </p>
          )}
        </section>
      )}
    </>
  );
}
