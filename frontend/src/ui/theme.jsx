import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/**
 * Theme: dark, light, or follow the operating system.
 *
 * "System" is the default rather than dark, because someone who has told
 * their OS they want light mode has already answered this question — and
 * this app gets opened next to a meeting, on whatever machine is to hand.
 *
 * The choice is written to `data-theme` on <html>, which is what the CSS
 * token overrides key off. Persisted so a reload doesn't undo it, and
 * live-updating when the OS preference changes while the app is open.
 */
const STORAGE_KEY = "nexvi.theme";
const ThemeContext = createContext(null);

function systemPrefersDark() {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

function readStored() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return ["dark", "light", "system"].includes(stored) ? stored : "system";
  } catch {
    // Private browsing and some embedded webviews throw on access.
    return "system";
  }
}

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(readStored);
  const [systemDark, setSystemDark] = useState(systemPrefersDark);

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return;
    const onChange = (event) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const resolved = preference === "system" ? (systemDark ? "dark" : "light") : preference;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
    // Tells the browser which scrollbar and form-control palette to use;
    // without it, native controls stay dark on a light page.
    document.documentElement.style.colorScheme = resolved;
  }, [resolved]);

  const choose = useCallback((next) => {
    setPreference(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* not fatal — the theme still applies for this session */
    }
  }, []);

  const value = useMemo(
    () => ({ preference, resolved, setTheme: choose }),
    [preference, resolved, choose]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside <ThemeProvider>");
  return context;
}

const OPTIONS = [
  ["light", "☀", "Light"],
  ["dark", "☾", "Dark"],
  ["system", "◐", "Match system"],
];

export function ThemeSwitch() {
  const { preference, setTheme } = useTheme();

  return (
    <div className="theme-switch" role="group" aria-label="Colour theme">
      {OPTIONS.map(([value, glyph, label]) => (
        <button
          key={value}
          type="button"
          title={label}
          aria-label={label}
          aria-pressed={preference === value}
          onClick={() => setTheme(value)}
        >
          <span aria-hidden="true">{glyph}</span>
        </button>
      ))}
    </div>
  );
}
