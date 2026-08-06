import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Cmd+K palette.
 *
 * The demo path is upload → review → approve → report → history, and
 * clicking through it costs seconds that are very visible when someone
 * is watching. This makes every destination one keystroke away.
 *
 * Matching is subsequence-based ("pm" finds "Past meetings") because
 * that is what people expect from a palette, and it forgives typing
 * ahead of the render.
 */
function matches(query, text) {
  if (!query) return true;
  const needle = query.toLowerCase();
  const haystack = text.toLowerCase();
  if (haystack.includes(needle)) return true;

  let index = 0;
  for (const char of haystack) {
    if (char === needle[index]) index += 1;
    if (index === needle.length) return true;
  }
  return false;
}

export default function CommandPalette({ open, onClose, commands }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  const visible = useMemo(
    () => commands.filter((c) => matches(query, `${c.label} ${c.group || ""} ${c.keywords || ""}`)),
    [commands, query]
  );

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // Focus after paint, or the browser drops it on a freshly mounted node.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => setActive(0), [query]);

  useEffect(() => {
    listRef.current
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  /**
   * Handled at the window, not on the input.
   *
   * Keying off the input meant Escape did nothing whenever focus had
   * drifted -- after clicking the backdrop, or if the autofocus lost a
   * race with the browser. A modal that will not close on Escape is a
   * trap, so the listener lives above whatever happens to have focus.
   */
  useEffect(() => {
    if (!open) return undefined;

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((i) => (visible.length ? (i + 1) % visible.length : 0));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((i) => (visible.length ? (i - 1 + visible.length) % visible.length : 0));
      } else if (event.key === "Enter") {
        event.preventDefault();
        const command = visible[active];
        if (command) {
          onClose();
          command.run();
        }
      }
    }

    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [open, visible, active, onClose]);

  if (!open) return null;

  return (
    <div
      className="palette-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search meetings and actions…"
          aria-label="Search commands"
          aria-activedescendant={visible[active] ? `cmd-${active}` : undefined}
        />

        <div className="palette-list" ref={listRef} role="listbox">
          {visible.length === 0 && (
            <div className="palette-empty">No matches for “{query}”</div>
          )}
          {visible.map((command, index) => (
            <div
              key={command.id}
              id={`cmd-${index}`}
              role="option"
              aria-selected={index === active}
              className="palette-item"
              onMouseEnter={() => setActive(index)}
              onMouseDown={(e) => {
                e.preventDefault();
                onClose();
                command.run();
              }}
            >
              <span aria-hidden="true">{command.icon || "›"}</span>
              <span>{command.label}</span>
              {command.group && <span className="hint">{command.group}</span>}
            </div>
          ))}
        </div>

        <div className="palette-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> select</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}

/**
 * Global shortcut handling.
 *
 * Ignores keystrokes typed into inputs — nothing is more annoying than a
 * single-letter shortcut firing while you are naming a meeting.
 */
export function useShortcuts(bindings) {
  useEffect(() => {
    function onKeyDown(event) {
      const target = event.target;
      const typing =
        target instanceof HTMLElement &&
        (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable);

      const combo = [
        event.metaKey || event.ctrlKey ? "mod+" : "",
        event.shiftKey && event.key.length > 1 ? "shift+" : "",
        event.key.toLowerCase(),
      ].join("");

      const handler = bindings[combo];
      if (!handler) return;
      // Modified combos still work while typing; bare letters do not.
      if (typing && !combo.startsWith("mod+")) return;

      event.preventDefault();
      handler(event);
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [bindings]);
}
