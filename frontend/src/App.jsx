import { useCallback, useEffect, useRef, useState } from "react";
import StartScreen from "./components/StartScreen.jsx";
import TutorScreen from "./components/TutorScreen.jsx";
import { generateTask } from "./lib/api.js";
import { clearSession, loadSession, newSession, saveSession } from "./lib/session.js";

// New learners see the start screen; a saved session resumes on the tutor screen (docs/gui.md §1).
export default function App() {
  const [session, setSession] = useState(() => loadSession());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const inFlight = useRef(false); // one generation at a time (each costs a Claude call)

  const fetchTask = useCallback(async (current) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    setError(null);
    try {
      const { level } = await generateTask(current.progress);
      const next = { ...current, level, board: null }; // a new task starts from its own board
      saveSession(next);
      setSession(next);
    } catch (e) {
      setError(e.message);
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, []);

  // Resume: a saved session without a task (e.g. reloaded mid-generation) fetches one.
  useEffect(() => {
    if (session && !session.level && !loading && !error) fetchTask(session);
  }, [session, loading, error, fetchTask]);

  const start = () => {
    const fresh = newSession();
    saveSession(fresh);
    setSession(fresh);
  };

  // Confirmation happens in the header (TutorScreen); this only wipes.
  const restart = () => {
    clearSession();
    setError(null);
    setSession(null);
  };

  // TEMPORARY (until the editor reports `solved`): Next counts the current task as solved,
  // records it in the history, raises the skill level and fetches the next task.
  const next = () => {
    const { level, progress } = session;
    const summary = {
      title: level.title,
      concept: level.concept,
      shape: level.shape ?? "",
      difficulty: level.difficulty ?? progress.skill_level,
      hints_used: 0,
      misconceptions: [],
      signature: level.signature ?? "",
    };
    const advanced = {
      ...session,
      progress: { skill_level: progress.skill_level + 1, history: [...progress.history, summary] },
      level: null, // the resume effect fetches the next task
      board: null,
      chat: [...(session.chat ?? []), { role: "notice", text: `Next task (after “${level.title}”)` }],
    };
    saveSession(advanced);
    setSession(advanced);
  };

  // The learner's edited board; null means the task's starting board.
  const setBoard = useCallback((board) => {
    setSession((current) => {
      const next = { ...current, board };
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

  if (!session) return <StartScreen onStart={start} />;
  return (
    <TutorScreen
      session={session}
      loading={loading}
      error={error}
      onRestart={restart}
      onRetry={() => fetchTask(session)}
      onChat={setChat}
      onNext={next}
      onBoard={setBoard}
    />
  );
}
