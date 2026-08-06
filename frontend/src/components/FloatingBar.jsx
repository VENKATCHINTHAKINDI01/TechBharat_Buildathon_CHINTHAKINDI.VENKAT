import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Naina's floating panel — the app's presence during a meeting.
 *
 * While a call is running you are looking at the Meet tab, not at
 * Nexvi.Meets, so the analysis has to come to you. This renders Naina's
 * live view — transcript, detected commitments, recording controls — in a
 * small always-on-top window.
 *
 * Two mechanisms, in order of preference:
 *
 * 1. **Document Picture-in-Picture** (Chrome/Edge 116+). A real OS-level
 *    always-on-top window that survives switching tabs — the only option
 *    that genuinely stays visible over the meeting. React renders into it
 *    through a portal, so it is the same component tree and stays live
 *    with no message passing.
 * 2. **In-page draggable panel** — the fallback, honest about only
 *    floating above this tab.
 *
 * Styles are copied into the PiP document explicitly: a separate document
 * inherits no stylesheets from its opener.
 */
export default function FloatingBar({
  segments,
  candidates,
  tracks,
  meetingId,
  paused,
  onPause,
  onResume,
  onEnd,
  onClose,
}) {
  const [pipWindow, setPipWindow] = useState(null);
  const [pos, setPos] = useState({ x: window.innerWidth - 390, y: 76 });
  const feedRef = useRef(null);

  const supportsPip = typeof window !== "undefined" && "documentPictureInPicture" in window;

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight });
  }, [segments]);

  const openPip = useCallback(async () => {
    if (!supportsPip) return;
    try {
      const win = await window.documentPictureInPicture.requestWindow({
        width: 390,
        height: 560,
      });

      [...document.styleSheets].forEach((sheet) => {
        try {
          const css = [...sheet.cssRules].map((r) => r.cssText).join("");
          const style = win.document.createElement("style");
          style.textContent = css;
          win.document.head.appendChild(style);
        } catch {
          if (sheet.href) {
            const link = win.document.createElement("link");
            link.rel = "stylesheet";
            link.href = sheet.href;
            win.document.head.appendChild(link);
          }
        }
      });

      win.document.body.style.margin = "0";
      win.document.body.style.background = "var(--bg, #0f1115)";
      win.document.title = "Naina — Nexvi.Meets";
      win.addEventListener("pagehide", () => setPipWindow(null));
      setPipWindow(win);
    } catch (err) {
      console.warn("[FloatingBar] Picture-in-Picture refused", err);
    }
  }, [supportsPip]);

  function startDrag(event) {
    if (pipWindow) return;
    const offsetX = event.clientX - pos.x;
    const offsetY = event.clientY - pos.y;
    const move = (e) =>
      setPos({
        x: Math.max(0, Math.min(window.innerWidth - 360, e.clientX - offsetX)),
        y: Math.max(0, Math.min(window.innerHeight - 120, e.clientY - offsetY)),
      });
    const stop = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
  }

  const eligible = candidates.filter((c) => c.gate.eligible).length;
  const recent = segments.slice(-14);

  const body = (
    <div className={pipWindow ? "floating pip" : "floating"}>
      <div className="floating-head" onMouseDown={startDrag} style={{ cursor: pipWindow ? "default" : "grab" }}>
        <span className={`naina-dot ${paused ? "" : "live"}`} aria-hidden="true">N</span>
        <div style={{ lineHeight: 1.2 }}>
          <strong style={{ fontSize: 12 }}>Naina</strong>
          <div className="tiny muted">{paused ? "paused" : "listening"}</div>
        </div>
        <span className="spacer" />
        {!pipWindow && supportsPip && (
          <button className="ghost tiny" onClick={openPip} title="Keep this on top of your meeting">
            ⧉
          </button>
        )}
        {onClose && !pipWindow && (
          <button className="ghost tiny" onClick={onClose} title="Hide">
            ✕
          </button>
        )}
      </div>

      {/* recording controls */}
      <div className="floating-controls">
        {paused ? (
          <button className="primary tiny" onClick={onResume}>
            ● Resume
          </button>
        ) : (
          <button className="tiny" onClick={onPause}>
            ⏸ Pause
          </button>
        )}
        <button className="danger tiny" onClick={onEnd}>
          ■ End &amp; report
        </button>
        <span className="spacer" />
        <span className={`pill ${paused ? "warn" : "ok"}`}>{paused ? "paused" : "● rec"}</span>
      </div>

      {paused && (
        <div className="floating-paused">
          Nothing is being captured. Naina resumes only when you say so.
        </div>
      )}

      <div className="floating-stats">
        <span className={`pill ${tracks?.mic ? "ok" : ""}`}>mic</span>
        <span className={`pill ${tracks?.remote ? "ok" : "warn"}`}>tab</span>
        <span className="pill">{segments.length} lines</span>
        <span className="pill accent">{candidates.length} found</span>
        <span className={`pill ${eligible ? "ok" : ""}`}>{eligible} ready</span>
      </div>

      <div className="floating-feed" ref={feedRef}>
        {recent.length === 0 && (
          <p className="muted tiny">
            {paused ? "Paused." : "Naina is listening — with everyone's knowledge."}
          </p>
        )}
        {recent.map((s) =>
          s.track === "marker" ? (
            <div className="floating-marker tiny" key={s.segment_id}>
              {s.text}
            </div>
          ) : (
            <div className="floating-line" key={s.segment_id}>
              <span className={`who ${s.attributable ? "known" : "unknown"}`}>{s.speaker}</span>
              <span>{s.text}</span>
            </div>
          )
        )}
      </div>

      {candidates.length > 0 && (
        <div className="floating-items">
          {candidates.slice(-4).map((c) => (
            <div className={`floating-item ${c.gate.eligible ? "ok" : "blocked"}`} key={c.candidate_id}>
              <div className="tiny" style={{ fontWeight: 600 }}>{c.raw_text}</div>
              <div className="tiny muted">
                {c.current_state && <b>{c.current_state.replace("_", " ")}</b>}
                {c.current_state ? " · " : ""}
                {c.owner_name || "no owner"} · {c.due_date || "no date"}
                {c.was_renegotiated ? " · renegotiated" : ""}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="floating-foot">
        <span className="tiny muted" title={meetingId}>{meetingId}</span>
        <span className="spacer" />
        <span className="tiny muted">nothing is created without you</span>
      </div>
    </div>
  );

  if (pipWindow) return createPortal(body, pipWindow.document.body);

  return (
    <div
      className="floating-anchor"
      style={{ left: pos.x, top: pos.y }}
      role="complementary"
      aria-label="Naina — live meeting analysis"
    >
      {body}
      {!supportsPip && (
        <p className="tiny muted" style={{ padding: "0 10px 8px" }}>
          This browser can’t pop Naina out; she floats above this tab only. Chrome or Edge 116+
          can keep her on top of the meeting.
        </p>
      )}
    </div>
  );
}
