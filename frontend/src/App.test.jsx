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
  const welcome = { kind: "knowledge", icon: "📘", title: null, text: "Welcome! Current needs a complete path.", terms: [[9, 16]] };
  const fetch = mockFetch(ok({ level: LEVEL, welcome, difficulty: 3, rationale: "", attempts: 1 }));
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
  expect(screen.getByRole("button", { name: "Next" }).disabled).toBe(true); // until the task is solved
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetch.mock.calls[0][1].body).profile).toEqual({ topics: [] });
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).level.id).toBe("gen-1234");
  // The tutor's welcome is the first chat message, with its terms in bold.
  expect(screen.getByText("Current").closest(".tutor-message").classList.contains("kind-knowledge")).toBe(true);
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).chat).toEqual([{ role: "tutor", ...welcome }]);
});

test("research consent and a name are saved with the session and sent to the server", async () => {
  mockFetch(ok({ level: LEVEL, difficulty: 3, rationale: "", attempts: 1 }));
  render(<App />);
  expect(screen.queryByLabelText("Your name (optional)")).toBeNull(); // only after opting in
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.change(screen.getByLabelText("Your name (optional)"), { target: { value: " Ada " } });
  fireEvent.click(screen.getByRole("button", { name: "Start Learning" }));
  await screen.findByPlaceholderText("Ask the tutor…");
  const research = JSON.parse(localStorage.getItem(SESSION_KEY)).research;
  expect(research).toMatchObject({ consent: true, name: "Ada" });
  expect(research.learner_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(FakeSocket.last.sent[0]).toMatchObject({ type: "session.start", research });

  // The server's active time is kept with the consent, so the next task's session continues it.
  FakeSocket.last.serverSends({ type: "evaluation", seq: 0, evaluation: { status: "open_circuit", readings: {}, issues: [] },
                                research: { active_s: 312 } });
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).research).toEqual({ ...research, active_s: 312 });
});

test("a blank name gets a generated one; no consent records nothing", async () => {
  mockFetch(ok({ level: LEVEL, difficulty: 3, rationale: "", attempts: 1 }));
  const { unmount } = render(<App />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Start Learning" }));
  await screen.findByPlaceholderText("Ask the tutor…");
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).research.name).toMatch(/^\w+ \w+ \d{2}$/);
  unmount();
  localStorage.clear();

  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Start Learning" }));
  await screen.findByPlaceholderText("Ask the tutor…");
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).research).toEqual({ consent: false });
});

test("/start shows the start screen and keeps the saved progress", async () => {
  const saved = { progress: { skill_level: 4, history: [] }, level: LEVEL, chat: [] };
  localStorage.setItem(SESSION_KEY, JSON.stringify(saved));
  window.history.pushState(null, "", "/start");
  const fetch = mockFetch(ok({}));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Start Learning" }));
  expect(screen.getByRole("heading", { name: "Share the voltage" })).toBeDefined(); // back to the saved task
  expect(window.location.pathname).toBe("/");
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).progress.skill_level).toBe(4);
  expect(fetch).not.toHaveBeenCalled();
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

test("tutor messages are tinted by kind, and the learner profile is saved and sent back", async () => {
  const profile = { topics: [{ id: "current", name: "Current", type: "term", definition: "Flow of charge.",
                               introduced: 1, understanding: 1, explained: 1, source: "catalog" }] };
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [], profile }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  const ws = FakeSocket.last;
  expect(ws.sent[0]).toMatchObject({ type: "session.start", profile });

  const joined = { topics: [...profile.topics, { ...profile.topics[0], id: "voltmeter", name: "Voltmeter", explained: 0 }] };
  ws.serverSends({ type: "evaluation", seq: 0, evaluation: { status: "open_circuit", readings: {}, issues: [] }, profile: joined });
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).profile).toEqual(joined);

  ws.serverSends({ type: "tutor.started", request_id: "react-1", trigger: "reaction" });
  ws.serverSends({
    type: "tutor.message", request_id: "react-1", seq: 0,
    evaluation: { status: "open_circuit", readings: {}, issues: [] },
    message: { meta: { principle: "meter_usage", highlights: [], hint_level: 0, misconception: null },
               chat: { kind: "knowledge", icon: "📘", title: "Voltmeter", text: "A voltmeter goes across a part.",
                       terms: [[2, 11]] } },
    profile: joined,
  });
  const term = screen.getByText("voltmeter");
  expect(term.tagName).toBe("STRONG");
  const bubble = term.closest(".tutor-message");
  expect(bubble.querySelector(".body").textContent).toBe("VoltmeterA voltmeter goes across a part.");
  expect(bubble.classList.contains("kind-knowledge")).toBe(true);
  expect(bubble.querySelector(".icon").textContent).toBe("📘");
  expect(bubble.querySelector(".title").textContent).toBe("Voltmeter");
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).chat[0]).toMatchObject({ kind: "knowledge", icon: "📘", title: "Voltmeter" });
});

test("a tutor reaction arrives unprompted, and a failed one ends quietly", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [] }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  const ws = FakeSocket.last;
  ws.serverSends({ type: "tutor.started", request_id: "react-1", trigger: "reaction" });
  expect(screen.getByText("Tutor is thinking…")).toBeDefined();
  ws.serverSends({
    type: "tutor.message",
    request_id: "react-1",
    evaluation: { status: "open_circuit", readings: { VM1: 0 }, issues: [] },
    message: { meta: { principle: "closed_loop", highlights: [], hint_level: 0, misconception: null },
               chat: { kind: "question", text: "Where does the current go after R1?" } },
  });
  expect(screen.getByText("Where does the current go after R1?")).toBeDefined();

  ws.serverSends({ type: "tutor.started", request_id: "react-3", trigger: "reaction" });
  ws.serverSends({ type: "tutor.dropped", request_id: "react-3" }); // out of date: nothing is shown
  expect(screen.queryByText("Tutor is thinking…")).toBeNull();
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).chat.map((m) => m.role)).toEqual(["tutor"]);

  ws.serverSends({ type: "tutor.started", request_id: "react-2", trigger: "reaction" });
  ws.serverSends({ type: "error", code: "tutor_unavailable", message: "The tutor is unavailable right now; try again shortly.", request_id: null });
  expect(screen.queryByText("Tutor is thinking…")).toBeNull();
  expect(screen.queryByText("The tutor is unavailable right now; try again shortly.")).toBeNull();
  expect(JSON.parse(localStorage.getItem(SESSION_KEY)).chat.map((m) => m.role)).toEqual(["tutor"]);
});

test("a reply about an older board shows its text but not its readings", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [] }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  const ws = FakeSocket.last;
  const reply = (seq, reading, text) => ws.serverSends({
    type: "tutor.message", request_id: `react-${seq}`, seq,
    evaluation: { status: "open_circuit", readings: { VM1: reading }, issues: [] },
    message: { meta: { principle: "closed_loop", highlights: [], hint_level: 0, misconception: null },
               chat: { kind: "question", text } },
  });
  reply(3, 9, "About a board that has changed since.");
  expect(screen.getByText("About a board that has changed since.")).toBeDefined();
  expect(screen.getByLabelText("Task and targets").textContent).not.toContain("VM1: 9");
  reply(0, 7, "About the current board.");
  expect(screen.getByLabelText("Task and targets").textContent).toContain("VM1: 7");
});

test("the Hint button climbs the ladder, lights up when a hint is offered, and Next records it", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 2, history: [] }, level: LEVEL, chat: [] }));
  const fetch = mockFetch(ok({ level: { ...LEVEL, id: "gen-next", title: "Parallel paths" }, difficulty: 3, rationale: "", attempts: 1 }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  const ws = FakeSocket.last;
  expect(ws.sent[0]).toMatchObject({ type: "session.start", hint_level: 0 });
  const reply = (extra, meta) => ws.serverSends({
    type: "tutor.message", request_id: "r", seq: 0, ...extra,
    evaluation: { status: "open_circuit", readings: { VM1: 0 }, issues: [] },
    message: { meta: { principle: "closed_loop", highlights: [], hint_level: 0, misconception: null, ...meta },
               chat: { kind: "question", text: `Reply ${ws.sent.length}` } },
  });

  reply({ hint_offered: true }, {});
  const hint = screen.getByRole("button", { name: "Hint 1/3" });
  expect(hint.className).toContain("offered");
  fireEvent.click(hint);
  expect(ws.sent.at(-1)).toMatchObject({ type: "tutor.request", action: "hint" });
  expect(screen.getByText("Hint 1/3, please")).toBeDefined();
  expect(screen.getByRole("button", { name: "Hint 1/3" }).className).not.toContain("offered");
  reply({}, { hint_level: 1, misconception: "current_used_up" });
  expect(screen.getByRole("button", { name: "Hint 2/3" })).toBeDefined();

  solve();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByRole("heading", { name: "Parallel paths" });
  const summary = JSON.parse(fetch.mock.calls.at(-1)[1].body).history.at(-1);
  expect(summary).toMatchObject({ hints_used: 1, misconceptions: ["current_used_up"] });
  expect(screen.getByRole("button", { name: "Hint 1/3" })).toBeDefined(); // a fresh ladder
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

// The server reports the current board as solved.
const solve = () => FakeSocket.last.serverSends({
  type: "evaluation", seq: 0, evaluation: { status: "solved", readings: { VM1: 4 }, issues: [] },
});

test("Next unlocks when the task is solved: a checkmark shows and the hint points to Next", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 1, history: [] }, level: LEVEL, chat: [] }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  const next = screen.getByRole("button", { name: "Next" });
  expect(next.disabled).toBe(true);
  expect(screen.queryByLabelText("Solved")).toBeNull();
  solve();
  expect(next.disabled).toBe(false);
  expect(screen.getByLabelText("Solved")).toBeDefined();
  expect(document.querySelector(".hint-bar").textContent).toMatch(/^Solved! Press Next/);
  FakeSocket.last.serverSends({ type: "evaluation", seq: 1, evaluation: { status: "open_circuit", readings: { VM1: 0 }, issues: [] } });
  expect(next.disabled).toBe(true); // breaking the solution locks it again
  expect(screen.queryByLabelText("Solved")).toBeNull();
});

test("Next records the solved task, raises the level and fetches the next task", async () => {
  const solvedLevel = { ...LEVEL, shape: "V + 2R + VM", difficulty: 3, signature: "sig-1" };
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 2, history: [] }, level: solvedLevel, chat: [] }));
  const fetch = mockFetch(ok({ level: { ...LEVEL, id: "gen-next", title: "Parallel paths" }, difficulty: 3, rationale: "", attempts: 1 }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  solve();
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

test("Next with a ready task never shows the wait view; a slow one shows it after a moment", async () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 2, history: [] }, level: LEVEL, chat: [] }));
  mockFetch(ok({ level: { ...LEVEL, id: "gen-next", title: "Parallel paths" }, difficulty: 3, rationale: "", attempts: 1 }));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  solve();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.queryByText("Generating your task…")).toBeNull(); // the solved task stays on screen
  expect(await screen.findByRole("heading", { name: "Parallel paths" })).toBeDefined();
  expect(screen.queryByText("Generating your task…")).toBeNull();

  vi.useFakeTimers();
  try {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {}))); // never arrives
    solve();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.queryByText("Generating your task…")).toBeNull();
    act(() => vi.advanceTimersByTime(300));
    expect(screen.getByText("Generating your task…")).toBeDefined();
  } finally {
    vi.useRealTimers();
  }
});

test("the header shows the curriculum level and the task within it", () => {
  const level = { ...LEVEL, curriculum: { level: 2, task: 1, tasks: 2, concept: "Ohm's law" } };
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 3, history: [] }, level, chat: [] }));
  render(<App />);
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 2");
  expect(screen.getByText("Task 1 of 2")).toBeDefined();
});

test("while the next task loads, the header keeps the last curriculum level", async () => {
  const level = { ...LEVEL, curriculum: { level: 3, task: 2, tasks: 2, concept: "voltage divider" } };
  localStorage.setItem(SESSION_KEY, JSON.stringify({ progress: { skill_level: 7, history: [] }, level, chat: [] }));
  let arrive;
  vi.stubGlobal("fetch", vi.fn(() => new Promise((resolve) => { arrive = resolve; })));
  render(<App />);
  await screen.findByPlaceholderText("Ask the tutor…");
  solve();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 3"); // not skill_level 8
  const next = { ...LEVEL, id: "gen-next", title: "Parallel paths", curriculum: { level: 4, task: 1, tasks: 2, concept: "parallel" } };
  arrive(ok({ level: next, difficulty: 3, rationale: "", attempts: 1 }));
  await screen.findByRole("heading", { name: "Parallel paths" });
  expect(screen.getByLabelText("Skill level").textContent).toBe("Level 4");
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
