import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { parse } from "yaml";

// The root config.yaml decides at build time whether debug features are shown (public: false).
const config = parse(readFileSync(new URL("../config.yaml", import.meta.url), "utf8"));

const backend = `http://127.0.0.1:${process.env.BACKEND_PORT || 8000}`;

export default defineConfig({
  plugins: [react()],
  define: { __PUBLIC__: JSON.stringify(Boolean(config.public)) },
  server: {
    host: "127.0.0.1",
    port: Number(process.env.FRONTEND_PORT || 5173),
    strictPort: true,
    // The browser talks to one origin; the dev server forwards API and WebSocket traffic.
    proxy: {
      "/api": backend,
      "/ws": { target: backend.replace("http", "ws"), ws: true },
    },
  },
  test: {
    environment: "jsdom",
  },
});
