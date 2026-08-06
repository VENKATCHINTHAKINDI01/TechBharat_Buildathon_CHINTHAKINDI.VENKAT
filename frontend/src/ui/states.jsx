/**
 * Loading, empty and error states.
 *
 * These were the parts of the UI nobody designed: a bare "Loading…", a
 * one-line "no candidates", and errors that appeared as raw strings. They
 * are also the states a demo spends a surprising amount of time in.
 *
 * Skeletons rather than spinners, because a skeleton says what is coming
 * and keeps the layout from jumping when it arrives.
 */

export function Skeleton({ lines = 3, card = false }) {
  if (card) {
    return (
      <div aria-hidden="true">
        {Array.from({ length: lines }).map((_, i) => (
          <div className="skeleton skeleton-card" key={i} />
        ))}
      </div>
    );
  }
  return (
    <div aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          className="skeleton skeleton-line"
          key={i}
          // Ragged widths read as text; identical bars read as a table.
          style={{ width: `${92 - i * 14}%` }}
        />
      ))}
    </div>
  );
}

export function Loading({ label = "Loading", card = false, lines = 3 }) {
  return (
    <div role="status" aria-live="polite">
      <span className="muted">{label}…</span>
      <div style={{ marginTop: 12 }}>
        <Skeleton lines={lines} card={card} />
      </div>
    </div>
  );
}

export function EmptyState({ icon = "○", title, children, action }) {
  return (
    <div className="empty-state">
      <div className="es-icon" aria-hidden="true">{icon}</div>
      <div className="es-title">{title}</div>
      {children && <div className="es-body">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", detail, onRetry }) {
  return (
    <div className="error" role="alert">
      <strong>{title}</strong>
      {detail && (
        <div className="muted" style={{ marginTop: 6, wordBreak: "break-word" }}>
          {detail}
        </div>
      )}
      {onRetry && (
        <div className="actions">
          <button onClick={onRetry}>Try again</button>
        </div>
      )}
    </div>
  );
}

/**
 * A number that counts up to its value.
 *
 * Purely decorative, so it starts at the final value and only animates
 * when motion is allowed — the correct number is on screen either way.
 */
import { useEffect, useRef, useState } from "react";

export function AnimatedNumber({ value, duration = 600 }) {
  const [display, setDisplay] = useState(value);
  const frame = useRef();

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof value !== "number") {
      setDisplay(value);
      return;
    }

    const from = 0;
    const start = performance.now();
    const step = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      // easeOutCubic: fast to begin, settles rather than stops dead.
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(from + (value - from) * eased));
      if (progress < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [value, duration]);

  return <>{display}</>;
}
