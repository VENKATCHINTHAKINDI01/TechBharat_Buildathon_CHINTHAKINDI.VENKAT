import { useEffect, useState } from "react";
import { getAgentRun, getAgents } from "../api/client";

/**
 * Shows what the agent system actually did.
 *
 * "Agentic" should be inspectable rather than asserted, so this renders
 * the real recorded run: every agent, its status, how long it took, and
 * which tools it invoked — ending at the human-review interrupt that the
 * system cannot cross on its own.
 */
export default function AgentTrace({ meetingId }) {
  const [run, setRun] = useState(null);
  const [graph, setGraph] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    getAgentRun(meetingId).then(setRun).catch(() => setRun(null));
    getAgents().then(setGraph).catch(() => setGraph(null));
  }, [meetingId, open]);

  const statusClass = (s) =>
    s === "ok" ? "ok" : s === "interrupted" ? "accent" : s === "failed" ? "bad" : "warn";

  return (
    <section className="panel">
      <h2>Agent run</h2>
      <button className="ghost" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide" : "Show"} agent trace
      </button>

      {open && run && (
        <>
          <p className="muted" style={{ marginTop: 12 }}>
            runtime <strong>{run.runtime}</strong> · {run.steps.length} steps ·{" "}
            {run.total_ms}ms total
          </p>

          <div style={{ marginTop: 12 }}>
            {run.steps.map((step, i) => {
              const meta = graph?.agents?.find((a) => a.name === step.agent);
              return (
                <div className="candidate" key={`${step.agent}-${i}`} style={{ marginBottom: 8 }}>
                  <div className="meta" style={{ marginBottom: 6 }}>
                    <span className="pill accent">{i + 1}</span>
                    <strong style={{ fontSize: 14 }}>{step.agent}</strong>
                    <span className={`pill ${statusClass(step.status)}`}>{step.status}</span>
                    <span className="pill">{step.duration_ms}ms</span>
                    {step.tools_used?.map((t) => (
                      <span className="pill" key={t}>
                        🔧 {t}
                      </span>
                    ))}
                  </div>
                  {meta && <p className="muted" style={{ margin: "0 0 6px" }}>{meta.description}</p>}
                  {step.summary && <p style={{ margin: 0, fontSize: 13 }}>{step.summary}</p>}
                  {step.error && <div className="reasons">{step.error}</div>}
                </div>
              );
            })}
          </div>

          {graph?.note && <p className="muted">{graph.note}</p>}
        </>
      )}

      {open && !run && <p className="muted">No agent run recorded for this meeting.</p>}
    </section>
  );
}
