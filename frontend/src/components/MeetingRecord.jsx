/**
 * The structured meeting record the brief asks for: executive summary,
 * decisions, open questions, risks/blockers, action items.
 */
export default function MeetingRecord({ record }) {
  if (!record) return null;

  const buckets = [
    ["Action items", record.action_items],
    ["Decisions", record.decisions],
    ["Risks / blockers", record.risks_blockers],
    ["Open questions", record.open_questions],
  ];

  return (
    <section className="panel">
      <h2>Structured meeting record</h2>
      <p className="summary">{record.executive_summary}</p>
      <div className="buckets">
        {buckets.map(([label, items]) => (
          <div className="bucket" key={label}>
            <div className="n">{items?.length ?? 0}</div>
            <div className="k">{label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
