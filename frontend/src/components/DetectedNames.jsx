import { useLiveSession } from "../live/LiveSessionProvider";
import { useToast } from "../ui/toast";

/**
 * Names Naina read off the shared meeting screen.
 *
 * These are **proposals, not participants**. Until you accept one, the
 * name cannot own an action item — which is the same rule that applies
 * to an untagged voice or an unattributed recording, and for the same
 * reason: a guessed owner is exactly what the safety gate exists to
 * stop, and a name lifted off a video tile by OCR is a guess in a
 * confident font.
 *
 * The confidence figure is Tesseract's, and it is about how clearly the
 * *pixels* read — not about whether the string is a person. "Conference
 * Room 2" can be read at 99% confidence. That is why a human still says
 * yes.
 */
export default function DetectedNames({ compact = false }) {
  const {
    proposedNames, scanning, canReadScreen, roster,
    scanScreenForNames, confirmNames, dismissName,
  } = useLiveSession();
  const toast = useToast();

  if (!canReadScreen && proposedNames.length === 0) return null;

  async function scan() {
    const found = await scanScreenForNames();
    if (found.length === 0) {
      toast.info(
        "No new names on screen",
        "Naina found nothing she could read as a person's name. Everyone visible may " +
          "already be listed, or the tiles may be too small to read."
      );
    }
  }

  const accept = (names) => {
    confirmNames(names);
    toast.success(
      names.length === 1 ? `${names[0]} added` : `${names.length} people added`,
      "They can now own action items."
    );
  };

  const body = (
    <>
      <div className="actions" style={{ marginTop: 0 }}>
        <button onClick={scan} disabled={scanning}>
          {scanning ? "Reading the screen…" : "⌕ Find names on screen"}
        </button>
        {proposedNames.length > 1 && (
          <button
            className="primary"
            onClick={() => accept(proposedNames.map((p) => p.name))}
          >
            Add all {proposedNames.length}
          </button>
        )}
      </div>

      {proposedNames.length > 0 && (
        <div className="stagger" style={{ marginTop: 12 }}>
          {proposedNames.map((proposal) => (
            <div className="proposal" key={proposal.name}>
              <span className="proposal-name">{proposal.name}</span>
              <span
                className="pill"
                title="How clearly the text read, not how sure Naina is that this is a person"
              >
                {proposal.confidence}% legible
              </span>
              <span className="spacer" />
              <button className="primary tiny" onClick={() => accept([proposal.name])}>
                Add
              </button>
              <button
                className="ghost tiny"
                onClick={() => dismissName(proposal.name)}
                aria-label={`Dismiss ${proposal.name}`}
              >
                Not a person
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );

  if (compact) {
    return (
      <div className="floating-names">
        <div className="tiny muted" style={{ marginBottom: 6 }}>
          {proposedNames.length > 0
            ? `${proposedNames.length} name(s) seen on screen`
            : `${roster.length} in the room`}
        </div>
        {body}
      </div>
    );
  }

  return (
    <section className="panel">
      <h2>Who else is here?</h2>
      <p className="muted" style={{ marginTop: -8 }}>
        Naina can read the names on the meeting tiles. This happens entirely on your machine —
        no picture of your screen is ever uploaded — and nothing she reads counts until you
        accept it.
      </p>
      {body}
    </section>
  );
}
