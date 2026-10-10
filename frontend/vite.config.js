import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = `http://127.0.0.1:${process.env.BACKEND_PORT || 8000}`;

export default defineConfig({
  plugins: [react()],
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
