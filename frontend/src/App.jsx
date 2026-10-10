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
      const next = { ...current, level };
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

  if (!session) return <StartScreen onStart={start} />;
  return (
    <TutorScreen
      session={session}
      loading={loading}
      error={error}
      onRestart={restart}
      onRetry={() => fetchTask(session)}
    />
  );
}
