// Learner session in localStorage (docs/gui.md §1): survives reloads; Restart Learning wipes it.

const KEY = "schematics-tutor.session";

// { progress, level, board?, chat, profile, research, lastLevel? }: `lastLevel` is the previous task's curriculum
// level, shown in the header while the next task loads; `profile` is the learner profile, kept by the
// backend's reply composer and saved here between sessions (docs/design.md §4); `research` is the learner's
// consent for this session, { consent, learner_id?, name? } (docs/design.md §5).
export const newSession = (research = { consent: false }) =>
  ({ progress: { skill_level: 1, history: [] }, level: null, chat: [], profile: { topics: [] }, research });

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
