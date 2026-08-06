import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom implements neither of these, and both are load-bearing: the theme
// system reads matchMedia, and several components animate on mount.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}

window.scrollTo = () => {};
Element.prototype.scrollIntoView = vi.fn();
Element.prototype.scrollTo = vi.fn();
