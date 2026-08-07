import { useEffect, useRef, useState } from "react";
import { tabAudioSupport } from "../lib/audioCapture";
import { useLiveSession } from "../live/LiveSessionProvider";

/**
 * Live meeting mode — the full-screen view.
 *
 * This is now only a *view*. The websocket, the recorders and all session
 * state live in `LiveSessionProvider`, above the view switch, because a
 * meeting must survive you navigating to another tab. When this component
 * owned them, opening "Past meetings" mid-meeting unmounted it and
 * silently ended the recording.
 *
 * The floating bar is likewise rendered by the app, not here, so it can
 * follow you onto any screen with working pause and end controls.
 *
 * Nothing is created here. The session produces candidates and gate
 * verdicts; approval stays a separate, human, post-meeting step.
 */
export default function LivePanel({ onFinished }) {
  // Setup-form state is genuinely local: it only matters until the
  // session starts, and is meaningless afterwards.
  const [consent, setConsent] = useState(false);
  const [participants, setParticipants] = useState("Arjun\nRohit\nPriya");
  const [selfName, setSelfName] = useState("Arjun");
  const [captureTab, setCaptureTab] = useState(true);
  const [title, setTitle] = useState("Live standup");

  const {
    phase, meetingId, roster, segments, candidates, warnings, status, error,
    engines, tracks, paused, barHidden, setBarHidden,
    start: startSession, pause: pauseRecording, resume: resumeRecording,
    end: endMeeting, send, setError,
  } = useLiveSession();

  const browser = tabAudioSupport();
  const feedRef = useRef(null);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [segments]);

  async function start() {
    setError(null);
    if (!consent) {
      setError("Confirm that everyone in the meeting knows it is being captured.");
      return;
    }
    await startSession({
      title,
      participants: participants.split("\n").map((p) => p.trim()).filter(Boolean),
      selfName: selfName.trim(),
      captureTab,
      onEnded: null,
    });
  }

  const unattributed = segments.filter((s) => !s.attributable && !s.speaker_confirmed).length;

  // ---------------- setup ----------------
  if (phase === "idle") {
    return (
      <section className="panel">
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
          <span className="naina-dot lg" aria-hidden="true">N</span>
          <div>
            <h2 style={{ margin: 0 }}>Start a meeting with Naina</h2>
            <p className="muted" style={{ margin: "2px 0 0" }}>
              She listens, tracks every commitment as it changes, and drafts the follow-ups —
              but she never creates anything until you say so.
            </p>
          </div>
        </div>
        {error && <div className="error" style={{ marginTop: 16 }}>{error}</div>}

        <div className="row">
          <div className="field">
            <label htmlFor="live-title">Meeting title</label>
            <input id="live-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="live-self">Which one are you?</label>
            <input id="live-self" value={selfName} onChange={(e) => setSelfName(e.target.value)} />
          </div>
        </div>

        <div className="field">
          <label htmlFor="live-participants">Participants (one per line)</label>
          <textarea
            id="live-participants"
            value={participants}
            onChange={(e) => setParticipants(e.target.value)}
          />
          <p className="muted" style={{ marginTop: 6 }}>
            Only these people can own an action item. A name that isn’t here resolves to nobody
            rather than being guessed.
          </p>
        </div>

        <div className="field">
          <label className="pill" style={{ cursor: "pointer", gap: 8 }}>
            <input
              type="checkbox"
              style={{ width: "auto", margin: 0 }}
              checked={captureTab}
              onChange={(e) => setCaptureTab(e.target.checked)}
            />
            Also capture the meeting tab (needed to hear anyone but you)
          </label>
        </div>

        <div className="reasons" style={{ background: "transparent", border: "1px solid var(--border)" }}>
          <label style={{ cursor: "pointer", display: "flex", gap: 10, alignItems: "flex-start" }}>
            <input
              type="checkbox"
              style={{ width: "auto", marginTop: 3 }}
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <span style={{ color: "var(--text)", fontSize: 13 }}>
              <strong>Everyone in this meeting knows it is being captured.</strong> Recording people
              without their knowledge is unlawful in many places. This acknowledgement is written to
              the audit log.
            </span>
          </label>
        </div>

        <div className="actions">
          <button className="primary" onClick={start} disabled={!consent}>
            Start capturing
          </button>
        </div>
        {captureTab && browser.supported && (
          <div className="notice" style={{ marginTop: 12 }}>
            <strong>When the share dialog opens:</strong>
            <ol style={{ margin: "6px 0 0", paddingLeft: 20 }}>
              <li>
                Choose the <strong>“{browser.browser} Tab”</strong> option — not “Entire Screen”
                or “Window”.
              </li>
              <li>Pick the tab with your Meet/Zoom call.</li>
              <li>
                Tick <strong>“Also share tab audio”</strong> at the bottom, then click Share.
              </li>
            </ol>
            <p className="muted" style={{ margin: "8px 0 0" }}>
              That tickbox only appears for a tab. Without it the browser sends video only and
              nobody but you will be heard.
            </p>
          </div>
        )}

        {captureTab && !browser.supported && (
          <div className="error" style={{ marginTop: 12 }}>
            {browser.reason} You can still capture your own microphone, or type lines manually.
          </div>
        )}
      </section>
    );
  }

  // ---------------- live / finalizing / ended ----------------
  return (
    <>
      <section className="panel">
      <h2>{phase === "ended" ? "Meeting ended" : "Live meeting"}</h2>

      <div className="meta">
        {phase === "live" && paused && <span className="pill warn">‖ paused</span>}
        {phase === "live" && !paused && <span className="pill ok">● recording</span>}
        {phase === "finalizing" && <span className="pill warn">finalizing…</span>}
        {phase === "ended" && <span className="pill accent">done</span>}
        <span className="pill">{meetingId}</span>
        <span className={`pill ${tracks.mic ? "ok" : ""}`}>mic {tracks.mic ? "on" : "off"}</span>
        <span className={`pill ${tracks.remote ? "ok" : "warn"}`}>
          tab {tracks.remote ? "on" : "off"}
        </span>
        {engines.transcriber && <span className="pill">stt: {engines.transcriber}</span>}
        <span className="pill">{segments.length} lines</span>
        <span className="pill accent">{candidates.length} commitments</span>
        {unattributed > 0 && <span className="pill warn">{unattributed} untagged</span>}
      </div>

      {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}
      {warnings.map((w) => (
        <div className="notice" key={w}>
          {w}
        </div>
      ))}
      {phase === "finalizing" && status && <div className="notice">Finalizing: {status}</div>}
      {phase === "ended" && status && (
        <div className="summary" style={{ marginTop: 12 }}>
          {status}
        </div>
      )}

      {phase === "live" && (
        <>
          {paused && (
            <div className="notice" style={{ marginTop: 12 }}>
              <strong>Recording paused.</strong> Nothing is being captured or transcribed — the
              microphone and tab audio are both off. The transcript will show a gap here rather
              than pretending the silence was silence.
            </div>
          )}
          <div className="actions">
            {paused ? (
              <button className="primary" onClick={resumeRecording}>
                ● Resume recording
              </button>
            ) : (
              <button onClick={pauseRecording}>⏸ Pause recording</button>
            )}
            <button onClick={() => send({ type: "flush" })} disabled={paused}>
              Extract now
            </button>
            {barHidden && (
              <button className="ghost" onClick={() => setBarHidden(false)}>
                Show Naina
              </button>
            )}
            <button className="danger" onClick={endMeeting}>
              ■ End meeting
            </button>
          </div>
        </>
      )}

      {phase === "ended" && meetingId && (
        <div className="actions">
          <button className="primary" onClick={() => onFinished?.(meetingId)}>
            Review &amp; approve →
          </button>
        </div>
      )}

      {/* transcript */}
      <div className="drawer">
        <strong style={{ fontSize: 13 }}>Transcript</strong>
        {segments.length === 0 && (
          <p className="muted">Nothing captured yet. Start talking, or type a line below.</p>
        )}
        <div ref={feedRef} style={{ maxHeight: 300, overflowY: "auto", marginTop: 8 }}>
          {segments.map((s) => (
            s.track === "marker" ? (
              <div className="floating-marker tiny" key={s.segment_id} style={{ margin: "10px 0" }}>
                {s.text}
              </div>
            ) : (
            <blockquote className="evidence" key={s.segment_id}>
              <strong>{s.speaker}</strong>
              {s.speaker_confirmed && <span className="pill ok" style={{ marginLeft: 6 }}>tagged</span>}
              <div style={{ marginTop: 4 }}>{s.text}</div>
              <cite>
                {s.track} · {(s.start_ms / 1000).toFixed(0)}s{s.engine ? ` · ${s.engine}` : ""}
              </cite>
              {!s.attributable && !s.speaker_confirmed && roster.length > 0 && (
                <div className="meta" style={{ marginTop: 6 }}>
                  <span className="muted">Who said this?</span>
                  {roster.map((p) => (
                    <button
                      key={p.participant_id}
                      className="ghost"
                      style={{ padding: "2px 8px", fontSize: 11 }}
                      onClick={() =>
                        send({
                          type: "tag_speaker",
                          segment_id: s.segment_id,
                          participant_id: p.participant_id,
                        })
                      }
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              )}
            </blockquote>
            )
          ))}
        </div>
      </div>

      {/* manual entry — a demo should never hinge on venue audio */}
      {phase === "live" && !paused && (
        <form
          className="row"
          style={{ marginTop: 12 }}
          onSubmit={(e) => {
            e.preventDefault();
            const speaker = e.target.speaker.value.trim();
            const text = e.target.text.value.trim();
            if (!text) return;
            send({ type: "text", speaker: speaker || selfName, text });
            e.target.text.value = "";
          }}
        >
          <div className="field">
            <label htmlFor="manual-speaker">Speaker</label>
            <input id="manual-speaker" name="speaker" defaultValue={selfName} />
          </div>
          <div className="field">
            <label htmlFor="manual-text">Type a line (if audio isn’t available)</label>
            <input id="manual-text" name="text" placeholder="Yes, I'll send it by Friday" />
          </div>
        </form>
      )}

      {/* commitments */}
      {candidates.length > 0 && (
        <div className="drawer">
          <strong style={{ fontSize: 13 }}>Commitments detected</strong>
          {candidates.map((c) => (
            <div
              className={`candidate ${c.gate.eligible ? "eligible" : "blocked"}`}
              key={c.candidate_id}
              style={{ marginTop: 8 }}
            >
              <h3 style={{ marginBottom: 6 }}>{c.raw_text}</h3>
              <div className="meta">
                <span className={`pill ${c.classification === "confirmed" ? "ok" : "warn"}`}>
                  {c.classification}
                </span>
                <span className="pill">{c.owner_name || "no owner"}</span>
                <span className="pill">{c.due_date || "no date"}</span>
                <span className={`pill ${c.gate.eligible ? "ok" : "bad"}`}>
                  {c.gate.eligible ? "gate: eligible" : "gate: blocked"}
                </span>
              </div>
              {!c.gate.eligible && (
                <div className="reasons">
                  <ul>
                    {c.gate.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <p className="muted" style={{ marginTop: 14 }}>
        Naina surfaces commitments; she does not act on them. Nothing is created until you
        approve it in review.
      </p>
      </section>
    </>
  );
}
