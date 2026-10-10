import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import App from "./App.jsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows the title and a connected backend", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "ok" }) })));
  render(<App />);
  expect(screen.getByRole("heading", { name: "Schematics AI Tutor" })).toBeDefined();
  expect(await screen.findByText("connected")).toBeDefined();
});

test("reports an unreachable backend", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("down"))));
  render(<App />);
  expect(await screen.findByText("unreachable")).toBeDefined();
});
