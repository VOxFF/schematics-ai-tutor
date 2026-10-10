// Learning (tutor) screen layout from the sketch (docs/gui.md §2). The editor shows the
// received task JSON until the grid editor exists.

import { readableJson } from "../lib/jsonfmt.js";

const WIRE_PALETTE = ["Straight (horizontal)", "Straight (vertical)", "Corner", "T", "+"];

function Header({ progress, onRestart }) {
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
      <div className="actions">
        <button onClick={onRestart}>Restart Learning</button>
        <button className="primary" disabled title="Enabled when the task is solved">
          Next
        </button>
      </div>
    </header>
  );
}

function TaskPanel({ level }) {
  const targets = Object.entries(level?.board?.targets ?? {});
  return (
    <section className="panel task" aria-label="Task and targets">
      <h2>{level?.title ?? "Task"}</h2>
      <p>{level?.intro ?? "…"}</p>
      {targets.length > 0 && (
        <ul className="targets">
          {targets.map(([meter, target]) => (
            <li key={meter}>
              {meter}: <span className="muted">--</span> → {target.value ?? "pending"}
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

function Chat() {
  return (
    <aside className="panel chat" aria-label="Chat">
      <h3>Tutor</h3>
      <div className="messages muted">The tutor will talk to you here.</div>
      <input placeholder="Ask the tutor…" disabled />
    </aside>
  );
}

export default function TutorScreen({ session, loading, error, onRestart, onRetry }) {
  const { progress, level } = session;
  return (
    <div className="tutor">
      <Header progress={progress} onRestart={onRestart} />
      <TaskPanel level={level} />
      <div className="panel workspace">
        <div className="editor-column">
          <Editor level={level} loading={loading} error={error} onRetry={onRetry} />
          <div className="hint-bar">Click or drag an element on the grid, or drag one from the inventory</div>
        </div>
        <Inventory level={level} />
      </div>
      <Chat />
    </div>
  );
}
