import { useCallback, useEffect, useRef, useState } from "react";
import { openLiveSocket } from "../api/client";
import {
  TrackRecorder,
  captureMicrophone,
  captureTabAudio,
  isCaptureSupported,
} from "../lib/audioCapture";

/**
 * Live meeting mode.
 *
 * Captures your microphone and the shared meeting tab, transcribes both
 * in near-realtime, and surfaces commitments while people are still
 * talking. Remote speech starts unattributed — you tag who said it, and
 * tagging one segment tags the whole cluster.
 *
 * Nothing is created here. The session produces candidates and gate
 * verdicts; approval stays a separate, human, post-meeting step.
 */
export default function LivePanel({ onFinished }) {
  const [phase, setPhase] = useState("setup"); // setup | live | finalizing | ended
  const [consent, setConsent] = useState(false);
  const [participants, setParticipants] = useState("Arjun\nRohit\nPriya");
  const [selfName, setSelfName] = useState("Arjun");
  const [captureTab, setCaptureTab] = useState(true);
  const [title, setTitle] = useState("Live standup");

  const [meetingId, setMeetingId] = useState(null);
  const [roster, setRoster] = useState([]);
  const [segments, setSegments] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [engines, setEngines] = useState({});
  const [tracks, setTracks] = useState({ mic: false, remote: false });

  const socketRef = useRef(null);
  const recordersRef = useRef([]);
  const feedRef = useRef(null);

  const stopRecorders = useCallback(() => {
    recordersRef.current.forEach((r) => {
      try {
        r.stop();
      } catch {
        /* already stopped */
      }
    });
    recordersRef.current = [];
    setTracks({ mic: false, remote: false });
  }, []);

  useEffect(() => {
    return () => {
      stopRecorders();
      socketRef.current?.close();
    };
  }, [stopRecorders]);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [segments]);

  function send(payload) {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  }

  function applySnapshot(msg) {
    if (msg.segments) setSegments(msg.segments);
    if (msg.candidates) setCandidates(msg.candidates);
    if (msg.warnings) setWarnings(msg.warnings);
  }

  async function start() {
    setError(null);
    if (!consent) {
      setError("Confirm that everyone in the meeting knows it is being captured.");
      return;
    }
    if (!isCaptureSupported()) {
      setError("This browser cannot capture audio. Use Chrome or Edge.");
      return;
    }

    // Ask for devices BEFORE opening the socket: a refused permission
    // should not leave a half-started session on the server.
    let micStream = null;
    let tabStream = null;
    try {
      micStream = await captureMicrophone();
      if (captureTab) tabStream = await captureTabAudio();
    } catch (err) {
      micStream?.getTracks().forEach((t) => t.stop());
      setError(err.message);
      return;
    }

    const socket = openLiveSocket();
    socketRef.current = socket;

    socket.onopen = () => {
      send({
        type: "start",
        title,
        meeting_date: new Date().toISOString().slice(0, 10),
        participants: participants.split("\n").map((p) => p.trim()).filter(Boolean),
        self_participant: selfName.trim(),
        consent_acknowledged: true,
        consent_note: "Reviewer confirmed in-app that participants were informed.",
      });
    };

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "started": {
          setMeetingId(msg.meeting_id);
          setRoster(msg.participants || []);
          setEngines({ transcriber: msg.transcriber, extractor: msg.extractor });
          setPhase("live");
          if (!msg.audio_enabled) {
            setWarnings((w) => [
              ...w,
              "No speech-to-text engine is configured — set GROQ_API_KEY or SARVAM_API_KEY. You can still type lines below.",
            ]);
          }
          const chunkSeconds = msg.chunk_seconds || 6;
          const started = [];
          if (micStream) {
            const rec = new TrackRecorder(micStream, "mic", (c) => send({ type: "audio", ...c }), chunkSeconds);
            rec.start();
            started.push(rec);
            setTracks((t) => ({ ...t, mic: true }));
          }
          if (tabStream) {
            const rec = new TrackRecorder(tabStream, "remote", (c) => send({ type: "audio", ...c }), chunkSeconds);
            rec.start();
            started.push(rec);
            setTracks((t) => ({ ...t, remote: true }));
          }
          recordersRef.current = started;
          break;
        }
        case "segments":
          setSegments((prev) => [...prev, ...msg.segments]);
          break;
        case "snapshot":
        case "tagged":
          applySnapshot(msg);
          break;
        case "warnings":
          setWarnings(msg.warnings || []);
          break;
        case "finalizing":
          setPhase("finalizing");
          setStatus(msg.step);
          break;
        case "ended":
          stopRecorders();
          applySnapshot(msg);
          setPhase("ended");
          setStatus(msg.executive_summary || null);
          break;
        case "error":
          setError(msg.error);
          if (msg.code === "consent_required" || msg.code === "participants_required") {
            stopRecorders();
            setPhase("setup");
          }
          break;
        default:
          break;
      }
    };

    socket.onerror = () => setError("Websocket failed. Is the backend running on :8000?");
    socket.onclose = () => stopRecorders();
  }

  function endMeeting() {
    stopRecorders();
    setPhase("finalizing");
    setStatus("wrapping up");
    send({ type: "end" });
  }

  const unattributed = segments.filter((s) => !s.attributable && !s.speaker_confirmed).length;

  // ---------------- setup ----------------
  if (phase === "setup") {
    return (
      <section className="panel">
        <h2>Live meeting</h2>
        {error && <div className="error">{error}</div>}

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
        {captureTab && (
          <p className="muted" style={{ marginTop: 10 }}>
            Your browser will ask which tab to share — pick the Meet/Zoom tab and{" "}
            <strong>tick “Also share tab audio”</strong>. Without that tick the browser sends video
            only and nobody else will be heard.
          </p>
        )}
      </section>
    );
  }

  // ---------------- live / finalizing / ended ----------------
  return (
    <section className="panel">
      <h2>{phase === "ended" ? "Meeting ended" : "Live meeting"}</h2>

      <div className="meta">
        {phase === "live" && <span className="pill ok">● recording</span>}
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
        <div className="actions">
          <button onClick={() => send({ type: "flush" })}>Extract now</button>
          <button className="danger" onClick={endMeeting}>
            End meeting
          </button>
        </div>
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
          ))}
        </div>
      </div>

      {/* manual entry — a demo should never hinge on venue audio */}
      {phase === "live" && (
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
        Live mode surfaces commitments only. Nothing is created until you approve it in review.
      </p>
    </section>
  );
}
