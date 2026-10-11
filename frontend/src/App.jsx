import { useCallback, useEffect, useRef, useState } from "react";
import StartScreen from "./components/StartScreen.jsx";
import TutorScreen from "./components/TutorScreen.jsx";
import { generateTask } from "./lib/api.js";
import { PUBLIC } from "./lib/build.js";
import { randomName } from "./lib/names.js";
import { clearSession, loadSession, newSession, saveSession } from "./lib/session.js";

// New learners see the start screen; a saved session resumes on the tutor screen (docs/gui.md §1).
// Debug (hidden in a public build): /start shows the start screen without touching the saved
// session; Start Learning then returns to it, or starts fresh if there is none.
// How long Next keeps the finished task on screen while the next one arrives (see fetchTask).
const QUIET_MS = 300;

const previewStart = () => !PUBLIC && window.location.pathname === "/start";

export default function App() {
  const [session, setSession] = useState(() => loadSession());
  const [preview, setPreview] = useState(previewStart);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const inFlight = useRef(false); // one generation at a time (each costs a Claude call)

  // Fetch the task for `current` (a session without a task). With `quietMs`, the screen keeps
  // showing the previous task that long: a pre-generated task arrives at once, and switching to
  // the wait view and back would make the whole screen flicker. Slower tasks get the wait view.
  const fetchTask = useCallback(async (current, quietMs = 0) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    const wait = () => {
      setSession(current);
      setLoading(true);
    };
    const timer = quietMs ? setTimeout(wait, quietMs) : wait();
    try {
      const { level, welcome } = await generateTask(current.progress, current.profile);
      // A new task starts from its own board, with a fresh hint ladder (docs/tutor.md §3), and the
      // tutor's welcome in the chat (docs/gui.md §7).
      const chat = welcome ? [...(current.chat ?? []), { role: "tutor", ...welcome }] : current.chat;
      const next = { ...current, level, chat, board: null, hint_level: 0, hint_offered: false, misconceptions: [] };
      saveSession(next);
      setSession(next);
    } catch (e) {
      setSession(current);
      setError(e.message);
    } finally {
      clearTimeout(timer);
      inFlight.current = false;
      setLoading(false);
    }
  }, []);

  // Resume: a saved session without a task (e.g. reloaded mid-generation) fetches one.
  useEffect(() => {
    if (session && !session.level && !loading && !error) fetchTask(session);
  }, [session, loading, error, fetchTask]);

  // `choice`: { consent, name } from the start screen; a blank name gets a generated one.
  const start = ({ consent, name } = {}) => {
    if (preview) {
      window.history.replaceState(null, "", "/");
      setPreview(false);
      if (session) return; // back to the saved session, progress intact
    }
    const research = consent
      ? { consent: true, learner_id: crypto.randomUUID(), name: name?.trim() || randomName() }
      : { consent: false };
    const fresh = newSession(research);
    saveSession(fresh);
    setSession(fresh);
  };

  // Confirmation happens in the header (TutorScreen); this only wipes.
  const restart = () => {
    clearSession();
    setError(null);
    setSession(null);
  };

  // Next (enabled once the status is `solved`): records the solved task in the history,
  // raises the skill level and fetches the next task.
  const next = () => {
    if (inFlight.current) return;
    const { level, progress } = session;
    const summary = {
      title: level.title,
      concept: level.concept,
      shape: level.shape ?? "",
      difficulty: level.difficulty ?? progress.skill_level,
      hints_used: session.hint_level ?? 0,
      misconceptions: session.misconceptions ?? [],
      signature: level.signature ?? "",
    };
    const advanced = {
      ...session,
      progress: { skill_level: progress.skill_level + 1, history: [...progress.history, summary] },
      level: null, // saved without a task: a reload mid-fetch resumes by fetching it
      lastLevel: level.curriculum?.level, // the header shows it until the next task arrives
      board: null,
      chat: [...(session.chat ?? []), { role: "notice", text: `Next task (after “${level.title}”)` }],
    };
    saveSession(advanced);
    fetchTask(advanced, QUIET_MS);
  };

  // The learner's edited board; null means the task's starting board.
  const setBoard = useCallback((board) => {
    setSession((current) => {
      const next = { ...current, board };
      saveSession(next);
      return next;
    });
  }, []);

  // Update the current task's record (hint level, offered hint, misconceptions) and save it.
  const updateTask = useCallback((update) => {
    setSession((current) => {
      const next = { ...current, ...update(current) };
      saveSession(next);
      return next;
    });
  }, []);

  const setProfile = useCallback((profile) => {
    setSession((current) => {
      const next = { ...current, profile };
      saveSession(next);
      return next;
    });
  }, []);

  const setChat = useCallback((chat) => {
    setSession((current) => {
      const next = { ...current, chat };
      saveSession(next);
      return next;
    });
  }, []);

  if (!session || preview) return <StartScreen onStart={start} />;
  return (
    <TutorScreen
      session={session}
      loading={loading}
      error={error}
      onRestart={restart}
      onRetry={() => fetchTask(session)}
      onChat={setChat}
      onProfile={setProfile}
      onNext={next}
      onBoard={setBoard}
      onTask={updateTask}
    />
  );
}
