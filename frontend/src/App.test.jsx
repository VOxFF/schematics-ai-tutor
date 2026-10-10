import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import App from "./App.jsx";

const LEVEL = {
  id: "gen-1234",
  order: 1,
  title: "Share the voltage",
  concept: "voltage divider",
  intro: "Pick a resistor for the gap.",
  board: {
    grid: { columns: 12, rows: 8 },
    components: [],
    inventory: [{ id: "R2", type: "resistor", value: 20 }],
    wires: [],
    targets: { VM1: { value: null } },
  },
};
const SESSION_KEY = "schematics-tutor.session";

function mockFetch(response) {
  const fetch = vi.fn(() => Promise.resolve(response));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
const ok = (body) => ({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("a new learner sees the start screen, then gets a task", async () => {
  const fetch = mockFetch(ok({ level: LEVEL, difficulty: 3, rationale: "", attempts: 1 }));
  render(<App />);
  expect(screen.getByRole("button", { name: "Start Learning" })).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: "Start Learning" }));
  expect(await screen.findByRole("heading", { name: "Share the voltage" })).toBeDefined();
  expect(screen.getByLabelText("Editor").textContent).toContain('"id": "gen-1234"');
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 1");
  expect(screen.getByLabelText("Inventory").textContent).toContain("R2 resistor 20");
  expect(screen.getByRole("button", { name: "Next" }).disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).level.id).toBe("gen-1234");
});

test("a returning learner resumes on the tutor screen without a new request", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 4, history: [] }, level: LEVEL }));
  const fetch = mockFetch(ok({}));
  render(<App />);
  expect(screen.getByRole("heading", { name: "Share the voltage" })).toBeDefined();
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 4");
  expect(fetch).not.toHaveBeenCalled();
});

test("restart learning wipes the session and returns to the start screen", () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 2, history: [] }, level: LEVEL }));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Restart Learning" }));
  expect(screen.getByRole("button", { name: "Start Learning" })).toBeDefined();
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});

test("a failed generation shows the error and a retry button", async () => {
  mockFetch({ ok: false, status: 503, json: () => Promise.resolve({ detail: "Claude is not configured" }) });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Start Learning" }));
  expect(await screen.findByText("Claude is not configured")).toBeDefined();
  expect(screen.getByRole("button", { name: "Try again" })).toBeDefined();
});

test("the start screen shows eight learning path steps, the first current and the rest locked", () => {
  render(<App />);
  const steps = screen.getAllByRole("listitem").filter((li) => li.querySelector(".step"));
  expect(steps).toHaveLength(8);
  expect(steps[0].textContent).toBe("Closed LoopCurrent flows only around a complete loop");
  expect(steps[0].querySelector(".bolt")).not.toBeNull();
  expect(steps.slice(1).every((li) => li.querySelector(".lock"))).toBe(true);
});
