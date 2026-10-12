import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { parse } from "yaml";

// The root config.yaml decides at build time whether debug features are shown (public: false).
// SCHEMATICS_PUBLIC=true|false overrides it; the Dockerfile sets true for the deployed build.
const config = parse(readFileSync(new URL("../config.yaml", import.meta.url), "utf8"));
const isPublic = process.env.SCHEMATICS_PUBLIC ? process.env.SCHEMATICS_PUBLIC === "true" : Boolean(config.public);
// The grid editor's settings (config.yaml `editor`).
const editor = config.editor ?? {};

const backend = `http://127.0.0.1:${process.env.BACKEND_PORT || 8000}`;

export default defineConfig({
  plugins: [react()],
  define: { __PUBLIC__: JSON.stringify(isPublic), __EDITOR__: JSON.stringify(editor) },
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
