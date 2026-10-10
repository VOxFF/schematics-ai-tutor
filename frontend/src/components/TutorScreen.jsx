// Learning (tutor) screen layout from the sketch (docs/gui.md §2). The editor shows the
// received task JSON until the grid editor exists.

import { useEffect, useRef, useState } from "react";
import GridEditor from "../editor/GridEditor.jsx";
import { readableJson } from "../lib/jsonfmt.js";
import { useTutorSession } from "../lib/tutorSession.js";

const WIRE_PALETTE = ["Straight (horizontal)", "Straight (vertical)", "Corner", "T", "+"];

// Hidden but still taking space: invisible, unreachable by keyboard and screen readers.
const shownWhen = (visible) => (visible ? {} : { style: { visibility: "hidden" }, "aria-hidden": true, inert: true });

// Restart Learning asks for confirmation in place of the buttons (no browser popup).
function Header({ progress, curriculum, canNext, onNext, onRestart }) {
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
            Level {curriculum?.level ?? progress.skill_level}
          </span>
          {curriculum && (
            <span className="muted">
              Task {curriculum.task} of {curriculum.tasks}
            </span>
          )}
          <span className="muted">Tasks solved: {progress.history.length}</span>
        </div>
      </div>
      {/* Both states share one grid cell, so the header never changes size when switching. */}
      <div className="actions-slot">
        <div className="actions" {...shownWhen(!confirming)}>
          <button onClick={() => setConfirming(true)}>Restart Learning</button>
          {/* TEMPORARY: always enabled; will require status `solved`. */}
          <button className="primary" disabled={!canNext} onClick={onNext} title="Temporary: counts the task as solved">
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
      {/* Text scrolls when long; targets keep their own column. */}
      <div className="task-text">
        <h2>{level?.title ?? "Task"}</h2>
        <p>{level?.intro ?? "Your next task is on its way…"}</p>
      </div>
      <div className="task-targets" aria-label="Targets">
        <h3>Targets</h3>
        {targets.length === 0 && <p className="muted">--</p>}
        <ul className="targets">
          {targets.map(([meter, target]) => (
            <li key={meter}>
              {meter}: <span className="muted">{readings[meter] ?? "--"}</span> → {target.value ?? "pending"}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Editor({ level, evaluation, loading, error, startError, onRetry }) {
  const [showJson, setShowJson] = useState(false);
  let body;
  if (loading)
    body = (
      <div className="editor-wait" role="status">
        <div className="spinner" aria-hidden="true" />
        <p>Generating your task…</p>
        <p className="muted">This can take about half a minute.</p>
      </div>
    );
  else if (startError)
    body = (
      <div className="error">
        <p>This saved task can't be resumed, probably after an update. Your progress and chat are kept.</p>
        <p className="muted">{startError}</p>
        <button onClick={onRetry}>Get a new task</button>
      </div>
    );
  else if (error)
    body = (
      <div className="error">
        <p>{error}</p>
        <button onClick={onRetry}>Try again</button>
      </div>
    );
  else if (level)
    body = (
      <>
        {showJson ? (
          <pre className="json">{readableJson(level)}</pre>
        ) : (
          <GridEditor board={level.board} readings={evaluation?.readings} />
        )}
        <button className="json-toggle" onClick={() => setShowJson((v) => !v)}>
          {showJson ? "Grid" : "JSON"}
        </button>
      </>
    );
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

export default function TutorScreen({ session, loading, error, onRestart, onRetry, onChat, onNext }) {
  const { progress, level } = session;
  const chat = session.chat ?? [];
  const tutor = useTutorSession(level, chat, onChat);
  return (
    <div className="tutor">
      <Header
        progress={progress}
        curriculum={level?.curriculum}
        canNext={Boolean(level) && !loading}
        onNext={onNext}
        onRestart={onRestart}
      />
      <TaskPanel level={level} evaluation={tutor.evaluation} />
      <div className="panel workspace">
        <div className="editor-column">
          <Editor
            level={level}
            evaluation={tutor.evaluation}
            loading={loading}
            error={error}
            startError={tutor.startError}
            onRetry={onRetry}
          />
          <div className="hint-bar">Click or drag an element on the grid, or drag one from the inventory</div>
        </div>
        <Inventory level={level} />
      </div>
      <Chat chat={chat} connected={tutor.connected} thinking={tutor.thinking} onSend={tutor.send} />
    </div>
  );
}
