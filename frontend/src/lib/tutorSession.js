// WebSocket session with the backend (docs/contract.md §1): session.start, tutor.request.
// Self-healing: reconnects on close, re-sends session.start and repeats the request when the
// server has lost the session (no_session), and reports a saved task the server rejects.
import { useCallback, useEffect, useRef, useState } from "react";

const RECONNECT_MS = 2000;
const REFUSED_RECONNECT_MS = 30000; // the server refused the session (1008: too many from this network)

function socketUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/session`;
}

// level: the current Level (or null); chat: [{role, text, kind?}]; onChat: (nextChat) => void;
// board: the learner's current board, sent on every change so the evaluation stays live;
// progress: sent with session.start, so the server can pre-generate the task after this one;
// hintLevel: the hint level reached in this task, sent with session.start so the ladder continues;
// onReply(meta, hintOffered): each tutor reply's metadata, for the task's hint and misconception record.
export function useTutorSession(level, chat, onChat, board, progress, { hintLevel = 0, onReply } = {}) {
  const [connected, setConnected] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const [startError, setStartError] = useState(null);
  // The latest tutor message's highlights and the board they were made for: any edit clears them
  // (the new evaluation arrives at once; Claude's follow-up brings new highlights).
  const [marked, setMarked] = useState({ highlights: [], board: null });
  const socket = useRef(null);
  const pending = useRef(null); // { request_id, action, learner_text?, replayed }
  const chatRef = useRef(chat);
  chatRef.current = chat;
  const levelRef = useRef(level);
  levelRef.current = level;
  const boardRef = useRef(board);
  boardRef.current = board;
  const progressRef = useRef(progress);
  progressRef.current = progress;
  const hintRef = useRef(hintLevel);
  hintRef.current = hintLevel;
  const onReplyRef = useRef(onReply);
  onReplyRef.current = onReply;
  const seq = useRef(0);

  const append = useCallback((entry) => onChat([...chatRef.current, entry]), [onChat]);

  const startSession = useCallback((ws) => {
    // History for the tutor: chat without errors and without a message that is about to be repeated.
    const history = chatRef.current
      .filter((m) => m.role === "learner" || m.role === "tutor")
      .filter((m, i, all) => !(pending.current && i === all.length - 1 && m.role === "learner"))
      .map(({ role, text }) => ({ role, text }));
    seq.current = 0; // a new server session numbers boards from 0 (its session.start board)
    ws.send(JSON.stringify({ type: "session.start", level: levelRef.current, board: boardRef.current, history,
                             progress: progressRef.current, hint_level: hintRef.current }));
  }, []);

  // A message (`text`) or a hint request (`text` undefined).
  const sendRequest = useCallback((ws, action, text) => {
    const request = { request_id: crypto.randomUUID(), action, ...(text ? { learner_text: text } : {}) };
    pending.current = { ...request, replayed: pending.current?.replayed ?? false };
    ws.send(JSON.stringify({ type: "tutor.request", ...request }));
  }, []);

  useEffect(() => {
    if (!level) return undefined;
    let closed = false;
    let retry;
    setStartError(null);
    setEvaluation(null); // the previous task's status must not carry over (it would unlock Next)
    setMarked({ highlights: [], board: null });

    const open = () => {
      const ws = new WebSocket(socketUrl());
      socket.current = ws;
      ws.onopen = () => {
        setConnected(true);
        startSession(ws);
      };
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "evaluation") setEvaluation(message.evaluation);
        else if (message.type === "tutor.started") setThinking(true);
        else if (message.type === "tutor.message") {
          pending.current = null;
          setThinking(false);
          append({ role: "tutor", kind: message.message.chat.kind, text: message.message.chat.text });
          onReplyRef.current?.(message.message.meta ?? {}, Boolean(message.hint_offered));
          // The reply is about board `seq`. After a newer edit, the fast evaluation already shows
          // the current readings, and the highlights would point at a board that's gone.
          if ((message.seq ?? seq.current) === seq.current) {
            setEvaluation(message.evaluation);
            setMarked({ highlights: message.message.meta?.highlights ?? [], board: boardRef.current });
          }
        } else if (message.type === "error") handleError(ws, message);
      };
      ws.onclose = (event) => {
        setConnected(false);
        setThinking(false);
        if (!closed) retry = setTimeout(open, event?.code === 1008 ? REFUSED_RECONNECT_MS : RECONNECT_MS);
      };
    };

    const handleError = (ws, message) => {
      if (message.code === "no_session") {
        // The server lost the session (e.g. it restarted): start again and repeat the message once.
        startSession(ws);
        const request = pending.current;
        if (request && !request.replayed) {
          pending.current = { ...request, replayed: true };
          sendRequest(ws, request.action, request.learner_text);
          return;
        }
      }
      if (message.code === "session_rejected") {
        setStartError(message.message);
        return;
      }
      pending.current = null;
      setThinking(false);
      if (message.request_id) append({ role: "error", text: message.message });
    };

    open();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
    // Reconnect only when the task changes, not on every chat update.
  }, [level?.id]);

  // Every edit: the server re-evaluates and replies with readings and status.
  useEffect(() => {
    const ws = socket.current;
    if (!board || !ws || ws.readyState !== WebSocket.OPEN) return;
    seq.current += 1;
    ws.send(JSON.stringify({ type: "board.update", seq: seq.current, board }));
  }, [board]);

  const send = useCallback(
    (text) => {
      const ws = socket.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !text.trim()) return false;
      append({ role: "learner", text: text.trim() });
      pending.current = null;
      sendRequest(ws, "message", text.trim());
      return true;
    },
    [append, sendRequest],
  );

  // The next step of the hint ladder; the server picks the level (docs/tutor.md §3).
  const askHint = useCallback(() => {
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    append({ role: "learner", kind: "hint", text: `Hint ${Math.min(hintRef.current + 1, 3)}/3, please` });
    pending.current = null;
    sendRequest(ws, "hint");
    return true;
  }, [append, sendRequest]);

  const highlights = marked.board === board ? marked.highlights : [];
  return { connected, thinking, evaluation, startError, highlights, send, askHint };
}
