import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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

// Fake WebSocket: records what the app sends and lets a test play the server.
class FakeSocket {
  static OPEN = 1;
  static last = null;
  constructor(url) {
    this.url = url;
    this.sent = [];
    this.readyState = 0;
    FakeSocket.last = this;
    setTimeout(() => {
      this.readyState = FakeSocket.OPEN;
      this.onopen?.();
    }, 0);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
  serverSends(message) {
    act(() => this.onmessage?.({ data: JSON.stringify(message) }));
  }
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("WebSocket", FakeSocket);
});
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
  expect(screen.getByRole("status").textContent).toContain("Generating your task"); // wait animation
  expect(await screen.findByRole("heading", { name: "Share the voltage" })).toBeDefined();
  expect(screen.queryByRole("status")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "JSON" })); // the grid needs WebGL; the JSON view doesn't
  expect(screen.getByLabelText("Editor").textContent).toContain('"id": "gen-1234"');
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 1");
  expect(screen.getByLabelText("R2 resistor 20 Ω")).toBeDefined(); // drawn as a symbol, named for a11y
  expect(screen.getByRole("button", { name: "Next" }).disabled).toBe(false); // temporary: always enabled
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

function renderSaved() {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 2, history: [] }, level: LEVEL }));
  render(<App />);
}

test("restart learning asks in place, then wipes the session and returns to the start screen", () => {
  renderSaved();
  fireEvent.click(screen.getByRole("button", { name: "Restart Learning" }));
  expect(screen.getByText("Your progress will be lost.")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Restart Learning" })).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Confirm" }));

  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(screen.getByRole("button", { name: "Start Learning" })).toBeDefined();
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});

test("cancel and Esc keep the session", () => {
  renderSaved();
  fireEvent.click(screen.getByRole("button", { name: "Restart Learning" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Next" })).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: "Restart Learning" }));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("button", { name: "Restart Learning" })).toBeDefined();
  expect(localStorage.getItem(SESSION_KEY)).not.toBeNull();
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

test("the learner chats with the tutor through the session socket", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [] }));
  render(<App />);
  const input = await screen.findByPlaceholderText("Ask the tutor…");
  const ws = FakeSocket.last;
  expect(ws.url).toMatch(/\/ws\/session$/);
  expect(ws.sent[0]).toMatchObject({ type: "session.start", level: { id: "gen-1234" }, history: [] });

  ws.serverSends({ type: "evaluation", seq: 0, evaluation: { status: "open_circuit", readings: { VM1: 0 }, issues: [] } });
  expect(screen.getByLabelText("Task and targets").textContent).toContain("VM1: 0");

  fireEvent.change(input, { target: { value: "Why is it zero?" } });
  fireEvent.submit(input.closest("form"));
  const request = ws.sent[1];
  expect(request).toMatchObject({ type: "tutor.request", action: "message", learner_text: "Why is it zero?" });
  expect(screen.getByText("Why is it zero?")).toBeDefined();

  ws.serverSends({ type: "tutor.started", request_id: request.request_id, trigger: "request" });
  expect(screen.getByText("Tutor is thinking…")).toBeDefined();
  ws.serverSends({
    type: "tutor.message",
    request_id: request.request_id,
    evaluation: { status: "open_circuit", readings: { VM1: 0 }, issues: [] },
    message: { meta: { principle: "closed_loop", highlights: [], hint_level: 0, misconception: null },
               chat: { kind: "question", text: "Does the current have a way back?" } },
  });
  expect(screen.queryByText("Tutor is thinking…")).toBeNull();
  expect(screen.getByText("Does the current have a way back?")).toBeDefined();
  const saved = JSON.parse(localStorage.getItem(SESSION_KEY)).chat;
  expect(saved.map((m) => m.role)).toEqual(["learner", "tutor"]);
});

test("a tutor error shows in the chat", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [] }));
  render(<App />);
  const input = await screen.findByPlaceholderText("Ask the tutor…");
  fireEvent.change(input, { target: { value: "hello" } });
  fireEvent.submit(input.closest("form"));
  const request = FakeSocket.last.sent[1];
  FakeSocket.last.serverSends({ type: "error", code: "rate_limited", message: "The tutor needs a moment; try again shortly.", request_id: request.request_id });
  expect(screen.getByText("The tutor needs a moment; try again shortly.")).toBeDefined();
});

test("after a server restart the session restarts and the message is repeated", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [] }));
  render(<App />);
  const input = await screen.findByPlaceholderText("Ask the tutor…");
  const ws = FakeSocket.last;
  fireEvent.change(input, { target: { value: "Still there?" } });
  fireEvent.submit(input.closest("form"));
  const first = ws.sent[1];

  ws.serverSends({ type: "error", code: "no_session", message: "send session.start first", request_id: first.request_id });
  const [restart, repeat] = ws.sent.slice(2);
  expect(restart).toMatchObject({ type: "session.start", history: [] }); // the pending message isn't duplicated
  expect(repeat).toMatchObject({ type: "tutor.request", learner_text: "Still there?" });
  expect(screen.queryByText("send session.start first")).toBeNull(); // the learner never sees it
});

test("a saved task the server rejects offers a new task, keeping progress", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 3, history: [] }, level: LEVEL, chat: [] }));
  const fetch = mockFetch(ok({ level: { ...LEVEL, id: "gen-new" }, difficulty: 2, rationale: "", attempts: 1 }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  FakeSocket.last.serverSends({ type: "error", code: "session_rejected", message: "target VM1: needs a numeric value", request_id: null });
  expect(screen.getByText(/can't be resumed/)).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: "Get a new task" }));
  fireEvent.click(await screen.findByRole("button", { name: "JSON" }));
  await screen.findByText(/"id": "gen-new"/);
  expect(JSON.parse(fetch.mock.calls[0][1].body).skill_level).toBe(3);
  expect(screen.queryByText(/can't be resumed/)).toBeNull();
});

test("Next (temporary) records the task, raises the level and fetches the next task", async () => {
  const solvedLevel = { ...LEVEL, shape: "V + 2R + VM", difficulty: 3, signature: "sig-1" };
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 2, history: [] }, level: solvedLevel, chat: [] }));
  const fetch = mockFetch(ok({ level: { ...LEVEL, id: "gen-next", title: "Parallel paths" }, difficulty: 3, rationale: "", attempts: 1 }));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Next" }));

  expect(await screen.findByRole("heading", { name: "Parallel paths" })).toBeDefined();
  const body = JSON.parse(fetch.mock.calls[0][1].body);
  expect(body.skill_level).toBe(3);
  expect(body.history).toEqual([{ title: "Share the voltage", concept: "voltage divider", shape: "V + 2R + VM",
                                  difficulty: 3, hints_used: 0, misconceptions: [], signature: "sig-1" }]);
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 3");
  expect(screen.getByText("Tasks solved: 1")).toBeDefined();
  expect(screen.getByText(/Next task \(after/)).toBeDefined();
});

test("the header shows the curriculum level and the task within it", () => {
  const level = { ...LEVEL, curriculum: { level: 2, task: 1, tasks: 2, concept: "Ohm's law" } };
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 3, history: [] }, level, chat: [] }));
  render(<App />);
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 2");
  expect(screen.getByText("Task 1 of 2")).toBeDefined();
});

test("dragging from the inventory: hint bar guides, Esc cancels, and the board goes to the session", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [] }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  expect(FakeSocket.last.sent[0]).toMatchObject({ type: "session.start", board: LEVEL.board }); // unedited: the task board
  const hintBar = () => document.querySelector(".hint-bar").textContent;
  expect(hintBar()).toMatch(/^Drag a part/);

  fireEvent.pointerDown(screen.getByLabelText("R2 resistor 20 Ω"));
  expect(hintBar()).toMatch(/^Drop onto the highlighted points/);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(hintBar()).toMatch(/^Drag a part/);

  fireEvent.pointerDown(screen.getByLabelText("Corner"));
  fireEvent.pointerUp(window); // released outside the grid: snaps back
  expect(hintBar()).toMatch(/^Drag a part/);
  expect(screen.getByLabelText("R2 resistor 20 Ω")).toBeDefined(); // still in the inventory
});
