import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * The floating meeting bar.
 *
 * During a call you are looking at the Meet tab, not at Nexvi.Meets — so
 * the analysis has to come to you. This renders a compact live view of
 * the transcript and detected commitments in a small always-on-top window.
 *
 * Two mechanisms, in order of preference:
 *
 * 1. **Document Picture-in-Picture** (Chrome/Edge 116+). A real OS-level
 *    always-on-top window that survives switching tabs — the only option
 *    that actually stays visible while you are in the meeting tab. React
 *    renders into it through a portal, so it is the same component tree
 *    and stays live without any message passing.
 *
 * 2. **In-page draggable panel** — the fallback. Honest about its limit:
 *    it only floats above *this* tab, so you would need the app
 *    side-by-side with the call.
 *
 * Styles are copied into the PiP document explicitly: a separate document
 * inherits no stylesheets from its opener.
 */
export default function FloatingBar({ segments, candidates, tracks, meetingId, onEnd, onClose }) {
  const [pipWindow, setPipWindow] = useState(null);
  const [pos, setPos] = useState({ x: window.innerWidth - 380, y: 80 });
  const dragRef = useRef(null);
  const feedRef = useRef(null);

  const supportsPip = typeof window !== "undefined" && "documentPictureInPicture" in window;

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight });
  }, [segments]);

  const openPip = useCallback(async () => {
    if (!supportsPip) return;
    try {
      const win = await window.documentPictureInPicture.requestWindow({
        width: 380,
        height: 520,
      });

      // A PiP document starts with no styles at all.
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
      win.document.title = "Nexvi.Meets — live";
      win.addEventListener("pagehide", () => setPipWindow(null));
      setPipWindow(win);
    } catch (err) {
      console.warn("[FloatingBar] Picture-in-Picture refused", err);
    }
  }, [supportsPip]);

  // Drag handling for the in-page fallback only.
  function startDrag(event) {
    if (pipWindow) return;
    const offsetX = event.clientX - pos.x;
    const offsetY = event.clientY - pos.y;
    const move = (e) =>
      setPos({
        x: Math.max(0, Math.min(window.innerWidth - 340, e.clientX - offsetX)),
        y: Math.max(0, Math.min(window.innerHeight - 100, e.clientY - offsetY)),
      });
    const stop = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    dragRef.current = true;
  }

  const eligible = candidates.filter((c) => c.gate.eligible).length;
  const recent = segments.slice(-14);

  const body = (
    <div className={pipWindow ? "floating pip" : "floating"}>
      <div
        className="floating-head"
        onMouseDown={startDrag}
        style={{ cursor: pipWindow ? "default" : "grab" }}
      >
        <span className="pill ok">● live</span>
        <strong style={{ fontSize: 12 }}>Nexvi.Meets</strong>
        <span className="spacer" />
        {!pipWindow && supportsPip && (
          <button className="ghost tiny" onClick={openPip} title="Pop out so it stays on top">
            ⧉ pop out
          </button>
        )}
        {onClose && !pipWindow && (
          <button className="ghost tiny" onClick={onClose}>
            ✕
          </button>
        )}
      </div>

      <div className="floating-stats">
        <span className={`pill ${tracks?.mic ? "ok" : ""}`}>mic</span>
        <span className={`pill ${tracks?.remote ? "ok" : "warn"}`}>tab</span>
        <span className="pill">{segments.length} lines</span>
        <span className="pill accent">{candidates.length} found</span>
        <span className={`pill ${eligible ? "ok" : ""}`}>{eligible} ready</span>
      </div>

      <div className="floating-feed" ref={feedRef}>
        {recent.length === 0 && <p className="muted tiny">Listening…</p>}
        {recent.map((s) => (
          <div className="floating-line" key={s.segment_id}>
            <span className={`who ${s.attributable ? "known" : "unknown"}`}>{s.speaker}</span>
            <span>{s.text}</span>
          </div>
        ))}
      </div>

      {candidates.length > 0 && (
        <div className="floating-items">
          {candidates.slice(-4).map((c) => (
            <div className={`floating-item ${c.gate.eligible ? "ok" : "blocked"}`} key={c.candidate_id}>
              <div className="tiny" style={{ fontWeight: 600 }}>{c.raw_text}</div>
              <div className="tiny muted">
                {c.owner_name || "no owner"} · {c.due_date || "no date"} ·{" "}
                {c.gate.eligible ? "ready to approve" : "blocked"}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="floating-foot">
        <span className="tiny muted" title={meetingId}>
          {meetingId}
        </span>
        <span className="spacer" />
        <button className="danger tiny" onClick={onEnd}>
          End meeting
        </button>
      </div>
    </div>
  );

  if (pipWindow) return createPortal(body, pipWindow.document.body);

  return (
    <div
      className="floating-anchor"
      style={{ left: pos.x, top: pos.y }}
      role="complementary"
      aria-label="Live meeting analysis"
    >
      {body}
      {!supportsPip && (
        <p className="tiny muted" style={{ padding: "0 10px 8px" }}>
          Your browser can’t pop this out; it floats above this tab only. Chrome or Edge 116+
          can keep it on top of the meeting.
        </p>
      )}
    </div>
  );
}
