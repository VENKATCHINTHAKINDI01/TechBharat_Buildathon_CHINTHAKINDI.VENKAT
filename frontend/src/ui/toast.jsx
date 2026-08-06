import { createContext, useCallback, useContext, useMemo, useState } from "react";

/**
 * Toasts.
 *
 * Approving an item used to give feedback only inside the card you were
 * looking at, which is invisible if you have already scrolled on. A
 * toast reports the outcome wherever you are.
 *
 * Errors do not auto-dismiss. A message you needed and missed is worse
 * than one you have to close, and error text here is often something the
 * user has to act on — a GitHub permission, a rate limit, a wait time.
 */
const ToastContext = createContext(null);
const DEFAULT_MS = 4500;

let nextId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    // Mark leaving first so the exit animation can run, then remove.
    setToasts((current) =>
      current.map((t) => (t.id === id ? { ...t, leaving: true } : t))
    );
    setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== id));
    }, 160);
  }, []);

  const push = useCallback(
    (toast) => {
      const id = ++nextId;
      const entry = { id, tone: "info", ...toast };
      setToasts((current) => [...current, entry]);

      if (entry.tone !== "error") {
        setTimeout(() => dismiss(id), entry.duration ?? DEFAULT_MS);
      }
      return id;
    },
    [dismiss]
  );

  const api = useMemo(
    () => ({
      push,
      dismiss,
      success: (title, message) => push({ tone: "ok", title, message }),
      error: (title, message) => push({ tone: "error", title, message }),
      warn: (title, message) => push({ tone: "warn", title, message }),
      info: (title, message) => push({ tone: "info", title, message }),
    }),
    [push, dismiss]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-viewport" role="region" aria-label="Notifications">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast ${toast.tone} ${toast.leaving ? "leaving" : ""}`}
            role={toast.tone === "error" ? "alert" : "status"}
          >
            <span aria-hidden="true">
              {{ ok: "✓", error: "✕", warn: "!", info: "•" }[toast.tone]}
            </span>
            <div className="toast-body">
              <div className="toast-title">{toast.title}</div>
              {toast.message && <div className="toast-message">{toast.message}</div>}
            </div>
            <button
              className="icon tiny"
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}
