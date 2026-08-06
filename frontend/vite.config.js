import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend talks to /api/*; the backend serves those routes at the
// root (/health, /meetings, /review), so the prefix is stripped here.
// That keeps the browser origin-relative in dev and lets the same build
// sit behind any reverse proxy in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,  // the live-meeting websocket rides the same prefix
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
