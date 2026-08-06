import { useEffect, useRef, useState } from "react";
import { openLiveSocket } from "../api/client";

const DEMO_LINES = [
  ["Arjun", "Rohit, can you finish the API migration by Friday?"],
  ["Rohit", "Yes, I will finish the API migration by Friday."],
  ["Arjun", "Priya, deployment checklist complete chesi Monday varaku share chesthava?"],
  ["Priya", "Yes, Monday morning ki పంపిస్తాను."],
];

/**
 * Live meeting mode.
 *
 * Commitments surface while the meeting is still running. Nothing is
 * created here — the session produces candidates and gate verdicts, and
 * approval remains a separate, human, post-meeting action.
 */
export default function LivePanel({ onFinished }) {
  const [connected, setConnected] = useState(false);
  const [feed, setFeed] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [note, setNote] = useState("");
  const [speaker, setSpeaker] = useState("Arjun");
  const [text, setText] = useState("");
  const [participants, setParticipants] = useState("Arjun\nRohit\nPriya");
  const [meetingId, setMeetingId] = useState(null);
  const [error, setError] = useState(null);
  const socketRef = useRef(null);

  useEffect(() => () => socketRef.current?.close(), []);

  function start() {
    setError(null);
    const socket = openLiveSocket();
    socketRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      socket.send(
        JSON.stringify({
          type: "start",
          title: "Live standup",
          meeting_date: new Date().toISOString().slice(0, 10),
          participants: participants.split("\n").map((p) => p.trim()).filter(Boolean),
        })
      );
    };

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "started") setMeetingId(msg.meeting_id);
      if (msg.type === "segment") setFeed((f) => [...f, msg]);
      if (msg.type === "snapshot" || msg.type === "ended") {
        setCandidates(msg.candidates || []);
        setNote(msg.note || "");
      }
      if (msg.type === "ended") {
        setConnected(false);
        onFinished?.(msg.meeting_id);
      }
      if (msg.type === "error") setError(msg.error);
    };

    socket.onclose = () => setConnected(false);
    socket.onerror = () => setError("Websocket connection failed. Is the backend running?");
  }

  function send(type, extra = {}) {
    socketRef.current?.send(JSON.stringify({ type, ...extra }));
  }

  function submitLine(e) {
    e.preventDefault();
    if (!text.trim()) return;
    send("segment", { speaker, text });
    setText("");
  }

  async function playDemo() {
    for (const [who, line] of DEMO_LINES) {
      send("segment", { speaker: who, text: line });
      await new Promise((r) => setTimeout(r, 400));
    }
    send("flush");
  }

  return (
    <section className="panel">
      <h2>Live meeting mode</h2>
      {error && <div className="error">{error}</div>}

      {!connected && !meetingId && (
        <>
          <div className="field">
            <label htmlFor="live-participants">Participants (one per line)</label>
            <textarea
              id="live-participants"
              value={participants}
              onChange={(e) => setParticipants(e.target.value)}
            />
          </div>
          <button className="primary" onClick={start}>
            Start live session
          </button>
        </>
      )}

      {connected && (
        <>
          <div className="meta">
            <span className="pill ok">live</span>
            <span className="pill">{meetingId}</span>
            <span className="pill">{feed.length} lines</span>
            <span className="pill accent">{candidates.length} candidates</span>
          </div>

          <form onSubmit={submitLine} className="row" style={{ marginTop: 12 }}>
            <div className="field">
              <label htmlFor="live-speaker">Speaker</label>
              <input id="live-speaker" value={speaker} onChange={(e) => setSpeaker(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="live-text">What was said</label>
              <input
                id="live-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Yes, I'll send it by Friday"
              />
            </div>
          </form>

          <div className="actions">
            <button onClick={submitLine}>Send line</button>
            <button className="ghost" onClick={playDemo}>
              Play demo transcript
            </button>
            <button className="ghost" onClick={() => send("flush")}>
              Extract now
            </button>
            <button className="danger" onClick={() => send("end")}>
              End meeting
            </button>
          </div>

          <div className="drawer">
            <strong style={{ fontSize: 13 }}>Transcript feed</strong>
            {feed.length === 0 && <p className="muted">Nothing captured yet.</p>}
            {feed.slice(-8).map((s) => (
              <blockquote className="evidence" key={s.segment_id}>
                <strong>{s.speaker}:</strong> {s.text}
                <cite>{s.segment_id}</cite>
              </blockquote>
            ))}
          </div>
        </>
      )}

      {candidates.length > 0 && (
        <div className="drawer">
          <strong style={{ fontSize: 13 }}>Commitments detected so far</strong>
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

      {note && <p className="muted" style={{ marginTop: 12 }}>{note}</p>}
    </section>
  );
}
