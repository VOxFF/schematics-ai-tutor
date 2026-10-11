// Backend calls. The dev server proxies /api to the backend (vite.config.js).

// `profile` (the learner profile) lets the backend compose the task's welcome message.
export async function generateTask(progress, profile) {
  const response = await fetch("/api/tasks/generate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ skill_level: progress.skill_level, history: progress.history, profile }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : body.detail?.message;
    throw new Error(detail || `Task generation failed (HTTP ${response.status})`);
  }
  return body;
}
