// Learner session in localStorage (docs/gui.md §1): survives reloads; Restart Learning wipes it.

const KEY = "schematics-tutor.session";

export const newSession = () => ({ progress: { skill_level: 1, history: [] }, level: null, chat: [] });

export function loadSession() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    localStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // Storage unavailable (private mode, quota): the session just won't survive a reload.
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}
