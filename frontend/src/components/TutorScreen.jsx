// Learning (tutor) screen layout from the sketch (docs/gui.md §2). The editor shows the
// received task JSON until the grid editor exists.

import { useEffect, useRef, useState } from "react";
import { readableJson } from "../lib/jsonfmt.js";
import { useTutorSession } from "../lib/tutorSession.js";

const WIRE_PALETTE = ["Straight (horizontal)", "Straight (vertical)", "Corner", "T", "+"];

// Hidden but still taking space: invisible, unreachable by keyboard and screen readers.
const shownWhen = (visible) => (visible ? {} : { style: { visibility: "hidden" }, "aria-hidden": true, inert: true });

// Restart Learning asks for confirmation in place of the buttons (no browser popup).
function Header({ progress, onRestart }) {
  const [confirming, setConfirming] = useState(false);
  const confirmButton = useRef(null);

  useEffect(() => {
    if (!confirming) return undefined;
    confirmButton.current?.focus();
    const cancelOnEsc = (e) => e.key === "Escape" && setConfirming(false);
    window.addEventListener("keydown", cancelOnEsc);
    return () => window.removeEventListener("keydown", cancelOnEsc);
  }, [confirming]);

  return (
    <header className="panel header">
      <div className="header-info">
        <div className="title">Schematics AI Tutor</div>
        <div className="header-meta">
          <span className="skill" aria-label="Skill level">
            Level {progress.skill_level}
          </span>
          <span className="muted">Tasks solved: {progress.history.length}</span>
        </div>
      </div>
      {/* Both states share one grid cell, so the header never changes size when switching. */}
      <div className="actions-slot">
        <div className="actions" {...shownWhen(!confirming)}>
          <button onClick={() => setConfirming(true)}>Restart Learning</button>
          <button className="primary" disabled title="Enabled when the task is solved">
            Next
          </button>
        </div>
        <div className="actions confirm" role="alertdialog" aria-label="Confirm restart" {...shownWhen(confirming)}>
          <span>Your progress will be lost.</span>
          <div className="confirm-buttons">
            <button onClick={() => setConfirming(false)}>Cancel</button>
            <button ref={confirmButton} className="danger" onClick={onRestart}>
              Confirm
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}

function TaskPanel({ level, evaluation }) {
  const targets = Object.entries(level?.board?.targets ?? {});
  const readings = evaluation?.readings ?? {};
  return (
    <section className="panel task" aria-label="Task and targets">
      <h2>{level?.title ?? "Task"}</h2>
      <p>{level?.intro ?? "…"}</p>
      {targets.length > 0 && (
        <ul className="targets">
          {targets.map(([meter, target]) => (
            <li key={meter}>
              {meter}: <span className="muted">{readings[meter] ?? "--"}</span> → {target.value ?? "pending"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Editor({ level, loading, error, onRetry }) {
  let body;
  if (loading) body = <p className="muted">Generating task… this can take about half a minute.</p>;
  else if (error)
    body = (
      <div className="error">
        <p>{error}</p>
        <button onClick={onRetry}>Try again</button>
      </div>
    );
  else body = <pre className="json">{readableJson(level)}</pre>;
  return (
    <section className="editor" aria-label="Editor">
      {body}
    </section>
  );
}

function Inventory({ level }) {
  const parts = level?.board?.inventory ?? [];
  return (
    <aside className="inventory" aria-label="Inventory">
      <h3>Inventory</h3>
      <ul>
        {parts.length === 0 && <li className="muted">No parts</li>}
        {parts.map((p) => (
          <li key={p.id}>
            {p.id} {p.type}
            {p.value != null ? ` ${p.value}` : ""}
          </li>
        ))}
      </ul>
      <h3>Wires</h3>
      <ul>
        {WIRE_PALETTE.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </aside>
  );
}

function Chat({ chat, connected, thinking, onSend }) {
  const [draft, setDraft] = useState("");
  const end = useRef(null);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [chat.length, thinking]);

  const submit = (e) => {
    e.preventDefault();
    if (onSend(draft)) setDraft("");
  };

  return (
    <aside className="panel chat" aria-label="Chat">
      <h3>Tutor</h3>
      <div className="messages" role="log" aria-live="polite">
        {chat.length === 0 && <p className="muted">Ask the tutor anything about circuits or this task.</p>}
        {chat.map((m, i) => (
          <div key={i} className={`${m.role}-message`}>
            {m.text}
          </div>
        ))}
        {thinking && <div className="muted thinking">Tutor is thinking…</div>}
        <div ref={end} />
      </div>
      <form onSubmit={submit}>
        <input
          aria-label="Message to the tutor"
          placeholder={connected ? "Ask the tutor…" : "Connecting…"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={!connected || thinking}
        />
      </form>
    </aside>
  );
}

export default function TutorScreen({ session, loading, error, onRestart, onRetry, onChat }) {
  const { progress, level } = session;
  const chat = session.chat ?? [];
  const tutor = useTutorSession(level, chat, onChat);
  return (
    <div className="tutor">
      <Header progress={progress} onRestart={onRestart} />
      <TaskPanel level={level} evaluation={tutor.evaluation} />
      <div className="panel workspace">
        <div className="editor-column">
          <Editor level={level} loading={loading} error={error} onRetry={onRetry} />
          <div className="hint-bar">Click or drag an element on the grid, or drag one from the inventory</div>
        </div>
        <Inventory level={level} />
      </div>
      <Chat chat={chat} connected={tutor.connected} thinking={tutor.thinking} onSend={tutor.send} />
    </div>
  );
}
