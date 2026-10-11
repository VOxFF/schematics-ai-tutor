// A public build (config.yaml `public: true`) hides debug features.
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import App from "./App.jsx";

vi.mock("./lib/build.js", () => ({ PUBLIC: true }));

class QuietSocket {
  static OPEN = 1;
  readyState = 0;
  send() {}
  close() {}
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("a public build has no JSON view in the editor", () => {
  vi.stubGlobal("WebSocket", QuietSocket);
  const level = { id: "gen-1", title: "Share the voltage", intro: "", concept: "voltage divider",
                  board: { grid: { columns: 12, rows: 8 }, components: [], inventory: [], wires: [], targets: {} } };
  localStorage.setItem("schematics-tutor.session", JSON.stringify({ progress: { skill_level: 1, history: [] }, level, chat: [] }));
  render(<App />);
  expect(screen.getByRole("button", { name: "Reset board" })).toBeDefined();
  expect(screen.queryByRole("button", { name: "JSON" })).toBeNull();
});
