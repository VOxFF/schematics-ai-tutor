// Learning (tutor) screen layout from the sketch (docs/gui.md §2). The editor shows the
// received task JSON until the grid editor exists.

import katex from "katex";
import "katex/dist/katex.min.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GridEditor from "../editor/GridEditor.jsx";
import { partName } from "../editor/naming.js";
import { lift, nextOrientation, place, removeSelected, rotateSelected, wirePalette } from "../editor/placement.js";
import { PUBLIC } from "../lib/build.js";
import { readableJson } from "../lib/jsonfmt.js";
import { MAX_HINT, useTutorSession } from "../lib/tutorSession.js";


// Hidden but still taking space: invisible, unreachable by keyboard and screen readers.
const shownWhen = (visible) => (visible ? {} : { style: { visibility: "hidden" }, "aria-hidden": true, inert: true });

// Restart Learning asks for confirmation in place of the buttons (no browser popup).
// `curriculum` is the task's ({ level, task, tasks }); while the next task loads it is null and
// `lastLevel` (the previous task's curriculum level) keeps the label steady: skill_level counts
// solved tasks, not curriculum levels, so showing it in between would make the label jump.
function Header({ progress, curriculum, lastLevel, canNext, onNext, onRestart }) {
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
            Level {curriculum?.level ?? lastLevel ?? progress.skill_level}
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
          <button className="primary" disabled={!canNext} onClick={onNext}
                  title={canNext ? "Go to the next task" : "Solve the task to continue"}>
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

function Editor({ level, palette, board, evaluation, loading, error, startError, onRetry, drag, onStartDrag, onDrop, onPlan, selected, onSelect, highlights, showJson, onToggleJson, onReset }) {
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
        {showJson && !PUBLIC ? (
          <pre className="json">{readableJson({ ...level, board })}</pre>
        ) : (
          <GridEditor board={board} startBoard={level.board}
                      readings={evaluation?.readings} drag={drag} onStartDrag={onStartDrag}
                      onDrop={onDrop} onPlan={onPlan} selected={selected} onSelect={onSelect}
                      highlights={highlights} palette={palette} />
        )}
        {evaluation?.status === "solved" && (
          // Non-blocking: the learner can still read the meters and the tutor's praise (docs/gui.md §4).
          <div className="solved-check" role="status" aria-label="Solved">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12.5l5 5L20 6.5" /></svg>
          </div>
        )}
        {/* Bottom-left corner of the editor field: free space beside the centered grid. */}
        <div className="editor-tools">
          <button onClick={onReset} title="Put the board back to the task's start">
            Reset board
          </button>
          {!PUBLIC && <button onClick={onToggleJson}>{showJson ? "Grid" : "JSON"}</button>}
        </div>
      </>
    );
  return (
    <section className="editor" aria-label="Editor">
      {body}
    </section>
  );
}

// The inventory is drawn inside the editor's scene (same scale as the board). This visually
// hidden list mirrors it for screen readers and keyboard users.
function InventoryList({ board, palette, onStartDrag }) {
  const start = (item) => (event) => {
    event.preventDefault();
    onStartDrag(item);
  };
  return (
    <ul className="sr-only" aria-label="Inventory">
      {palette.map((w) => (
        <li key={w.key} aria-label={w.label} onPointerDown={start({ kind: "wire", shape: w.shape, rotation: w.rotation })}>
          {w.label}
        </li>
      ))}
      {(board?.inventory ?? []).map((p) => (
        <li key={p.id} aria-label={partName(p)} onPointerDown={start({ kind: "part", ...p })}>
          {partName(p)}
        </li>
      ))}
    </ul>
  );
}

// Message text with the learner's topics in bold: `terms` are [start, end] spans of the whole
// text from the reply composer, in order and not overlapping (docs/gui.md §7). `from` and `to`
// pick one paragraph out of the text.
function withTerms(text, terms, from = 0, to = text.length) {
  const parts = [];
  let at = from;
  for (const [start, end] of terms ?? []) {
    if (start < at || end > to) continue;
    parts.push(text.slice(at, start), <strong key={start} className="term">{text.slice(start, end)}</strong>);
    at = end;
  }
  parts.push(text.slice(at, to));
  return parts;
}

// A tutor message's paragraphs, separated by a blank line in the text, each with its bold terms.
function Paragraphs({ text, terms }) {
  const blocks = [];
  let from = 0;
  for (const match of `${text}\n\n`.matchAll(/\n\n/g)) {
    if (match.index > from) blocks.push([from, match.index]);
    from = match.index + 2;
  }
  return blocks.map(([start, end]) => <p key={start} className="paragraph">{withTerms(text, terms, start, end)}</p>);
}

// `chat.formula`: lines of LaTeX drawn with KaTeX; a line it can't render shows as plain text.
function Formula({ lines }) {
  return (
    <div className="formula">
      {lines.map((line, i) => {
        try {
          const html = katex.renderToString(line, { displayMode: true, throwOnError: true, output: "html" });
          return <div key={i} className="formula-line" dangerouslySetInnerHTML={{ __html: html }} />;
        } catch {
          return <code key={i} className="formula-line plain">{line}</code>;
        }
      })}
    </div>
  );
}

// `hintLevel`: the hint rung reached in this task; the Hint button asks for the next one (docs/gui.md §7).
function Chat({ chat, connected, thinking, onSend, hintLevel, hintOffered, onHint }) {
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
          // Tutor messages are tinted by kind; the icon and title come from the reply composer.
          <div key={i} className={`${m.role}-message${m.role === "tutor" && m.kind ? ` kind-${m.kind}` : ""}`}>
            {m.role === "tutor" && m.icon && <span className="icon" aria-hidden="true">{m.icon}</span>}
            <div className="body">
              {m.role === "tutor" && m.title && <strong className="title">{m.title}</strong>}
              {m.role === "tutor" ? <Paragraphs text={m.text} terms={m.terms} /> : m.text}
              {m.role === "tutor" && m.formula?.length > 0 && <Formula lines={m.formula} />}
            </div>
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
        <button type="button" className={hintOffered ? "hint offered" : "hint"} onClick={onHint}
                disabled={!connected || thinking} title="Ask the tutor for a hint, one step at a time">
          Hint {Math.min(hintLevel + 1, MAX_HINT)}/{MAX_HINT}
        </button>
      </form>
    </aside>
  );
}

// Hint bar text for the current interaction (docs/gui.md §5); generated here, not by the backend.
// `selection` is { id, editable, blocked } for the selected element, or null.
function hint(drag, fits, selection, solved) {
  if (!drag && selection) {
    if (!selection.editable) return `${selection.id} is part of the task: it can't be moved, rotated or removed · Esc to deselect`;
    if (selection.blocked) return `Can't rotate ${selection.id} here: the turned part would overlap or leave the grid`;
    return `${selection.id} selected · drag to move · R to rotate · Del to remove · Esc to deselect`;
  }
  if (!drag && solved) return "Solved! Press Next for the next task, or keep exploring";
  if (!drag) return "Drag a part or a wire piece from the inventory onto the grid, or move one you placed";
  if (fits === false) return "Can't place here: the spot is taken or off the grid";
  return "Drop onto the highlighted points to connect · R to rotate · Esc to cancel";
}

export default function TutorScreen({ session, loading, error, onRestart, onRetry, onChat, onProfile, onResearch,
                                      onNext, onBoard, onTask }) {
  const { progress, level } = session;
  const chat = session.chat ?? [];
  const board = session.board ?? level?.board ?? null;
  const hintLevel = session.hint_level ?? 0;
  // Each reply updates the task's record: the hint level reached, an offered hint, misconceptions.
  const onReply = useCallback((meta, offered) => onTask?.((current) => ({
    hint_level: Math.max(current.hint_level ?? 0, meta.hint_level ?? 0),
    hint_offered: offered || (current.hint_offered && !meta.hint_level),
    misconceptions: meta.misconception && !(current.misconceptions ?? []).includes(meta.misconception)
      ? [...(current.misconceptions ?? []), meta.misconception] : current.misconceptions ?? [],
  })), [onTask]);
  const tutor = useTutorSession(level, chat, onChat, board, progress,
                                { hintLevel, onReply, profile: session.profile, onProfile, research: session.research,
                                  onResearch });
  const askHint = () => {
    if (tutor.askHint()) onTask?.(() => ({ hint_offered: false }));
  };
  // { item, rotation, base?, origin? }: `base` is the board without a placed element being moved,
  // `origin` its anchor and rotation before the move.
  const [drag, setDrag] = useState(null);
  const [fits, setFits] = useState(null);
  const [showJson, setShowJson] = useState(false);
  const [selected, setSelected] = useState(null); // { kind: "component" | "wire", id } on the board
  const [blocked, setBlocked] = useState(false); // the last R on the selection didn't fit
  const startBoard = level?.board;
  // The task's wire palette: straight always, other shapes only when the task removed one.
  const palette = useMemo(() => wirePalette(level?.wire_shapes), [level?.wire_shapes]);
  const solved = tutor.evaluation?.status === "solved"; // Next unlocks only then
  // The selection only counts while its element is on the board (e.g. not after Reset board).
  const selection = selected && board &&
    (selected.kind === "component" ? board.components : board.wires).some((x) => x.id === selected.id)
    ? selected : null;
  const editable = Boolean(selection && lift(board, selection, startBoard));
  const select = (next) => {
    setSelected(next);
    setBlocked(false);
  };

  useEffect(() => select(null), [level?.id]);

  // With a selection (and no drag): R rotates it in place, Del / Backspace removes it, Esc deselects.
  useEffect(() => {
    if (!selection || drag) return undefined;
    const key = (e) => {
      if (["INPUT", "TEXTAREA"].includes(e.target?.tagName)) return; // typing in the chat
      if (e.key === "Escape") select(null);
      else if ((e.key === "r" || e.key === "R") && editable) {
        const next = rotateSelected(board, selection, startBoard);
        setBlocked(!next);
        if (next) onBoard(next);
      } else if ((e.key === "Delete" || e.key === "Backspace") && editable) {
        e.preventDefault();
        select(null);
        onBoard(removeSelected(board, selection, startBoard));
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  // While dragging: R rotates, Esc cancels, releasing anywhere but the grid snaps back.
  useEffect(() => {
    if (!drag) return undefined;
    const key = (e) => {
      if (e.key === "Escape") setDrag(null);
      else if (e.key === "r" || e.key === "R") {
        setDrag((d) => d && { ...d, rotation: d.item.kind === "part" ? nextOrientation(d.rotation) : (d.rotation + 1) % 4 });
      }
    };
    const release = () => setDrag(null);
    window.addEventListener("keydown", key);
    window.addEventListener("pointerup", release);
    document.body.classList.add("dragging-item");
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("pointerup", release);
      document.body.classList.remove("dragging-item");
    };
  }, [drag]);

  const startDrag = (item) => setDrag({ item, rotation: item.kind === "part" ? "E" : item.rotation });
  const drop = (point) => {
    const origin = drag?.origin;
    const unmoved = origin && point[0] === origin.anchor[0] && point[1] === origin.anchor[1] && drag.rotation === origin.rotation;
    const next = drag && board && !unmoved && place(drag.base ?? board, drag.item, point, drag.rotation);
    setDrag(null);
    if (next) onBoard(next);
  };
  return (
    <div className="tutor">
      <Header
        progress={progress}
        curriculum={level?.curriculum}
        lastLevel={session.lastLevel}
        canNext={Boolean(level) && !loading && solved}
        onNext={onNext}
        onRestart={onRestart}
      />
      <TaskPanel level={level} evaluation={tutor.evaluation} />
      <div className="panel workspace">
        <div className="editor-column">
          <Editor
            level={level}
            palette={palette}
            board={drag?.base ?? board}
            drag={drag}
            onStartDrag={setDrag}
            onDrop={drop}
            onPlan={setFits}
            selected={selection}
            onSelect={select}
            highlights={tutor.highlights}
            showJson={showJson}
            onToggleJson={() => setShowJson((v) => !v)}
            onReset={() => onBoard(null)}
            evaluation={tutor.evaluation}
            loading={loading}
            error={error}
            startError={tutor.startError}
            onRetry={onRetry}
          />
          <div className="hint-bar" aria-live="polite">{hint(drag, fits, selection && { id: selection.id, editable, blocked }, solved)}</div>
        </div>
        <InventoryList board={board} palette={palette} onStartDrag={startDrag} />
      </div>
      <Chat chat={chat} connected={tutor.connected} thinking={tutor.thinking} onSend={tutor.send}
            hintLevel={hintLevel} hintOffered={Boolean(session.hint_offered)} onHint={askHint} />
    </div>
  );
}
