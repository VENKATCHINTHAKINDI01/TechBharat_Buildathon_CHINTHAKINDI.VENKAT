/**
 * Confidence, broken out per field.
 *
 * A single "0.62" tells a reviewer to be nervous without telling them
 * what to do. Splitting it says *which* part is weak — usually the owner
 * or the date — so the fix is obvious: open Edit, set that one field.
 * The weakest bar is highlighted because that is the one that decides
 * whether the safety gate lets this through.
 */
const LABELS = {
  text: "Wording",
  owner: "Owner",
  date: "Date",
  state: "Agreement",
};

const EXPLAIN = {
  text: "How clearly the transcript states this as a commitment.",
  owner: "How the owner was resolved — exact name, alias, pronoun, or not at all.",
  date: "Whether a real date was said, or inferred from something vague.",
  state: "Whether the commitment was actually settled, or left hanging.",
};

export default function FieldConfidence({ fields }) {
  const entries = Object.entries(fields || {});
  if (entries.length === 0) return null;

  const weakest = entries.reduce((a, b) => (b[1] < a[1] ? b : a))[0];

  return (
    <div className="fieldconf">
      {entries.map(([field, score]) => (
        <div
          className={`fc ${field === weakest ? "weak" : ""}`}
          key={field}
          title={EXPLAIN[field] || field}
        >
          <div className="fc-label">
            <span>{LABELS[field] || field}</span>
            <span>{score.toFixed(2)}</span>
          </div>
          <div className="fc-bar">
            <div className="fc-fill" style={{ width: `${Math.round(score * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}
