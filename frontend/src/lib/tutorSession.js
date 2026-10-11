// WebSocket session with the backend (docs/contract.md §1): session.start, tutor.request.
// Self-healing: reconnects on close, re-sends session.start and repeats the request when the
// server has lost the session (no_session), and reports a saved task the server rejects.
import { useCallback, useEffect, useRef, useState } from "react";
import { liveHighlights } from "../editor/highlights.js";

const RECONNECT_MS = 2000;

function socketUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/session`;
}

// level: the current Level (or null); chat: [{role, text, kind?}]; onChat: (nextChat) => void;
// board: the learner's current board, sent on every change so the evaluation stays live.
export function useTutorSession(level, chat, onChat, board) {
  const [connected, setConnected] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const [startError, setStartError] = useState(null);
  // The latest tutor message's highlights and the board they were made for.
  const [marked, setMarked] = useState({ highlights: [], board: null });
  const socket = useRef(null);
  const pending = useRef(null); // { request_id, learner_text, replayed }
  const chatRef = useRef(chat);
  chatRef.current = chat;
  const levelRef = useRef(level);
  levelRef.current = level;
  const boardRef = useRef(board);
  boardRef.current = board;
  const seq = useRef(0);

  const append = useCallback((entry) => onChat([...chatRef.current, entry]), [onChat]);

  const startSession = useCallback((ws) => {
    // History for the tutor: chat without errors and without a message that is about to be repeated.
    const history = chatRef.current
      .filter((m) => m.role === "learner" || m.role === "tutor")
      .filter((m, i, all) => !(pending.current && i === all.length - 1 && m.role === "learner"))
      .map(({ role, text }) => ({ role, text }));
    ws.send(JSON.stringify({ type: "session.start", level: levelRef.current, board: boardRef.current, history }));
  }, []);

  const sendRequest = useCallback((ws, text) => {
    const request = { request_id: crypto.randomUUID(), learner_text: text };
    pending.current = { ...request, replayed: pending.current?.replayed ?? false };
    ws.send(JSON.stringify({ type: "tutor.request", action: "message", ...request }));
  }, []);

  useEffect(() => {
    if (!level) return undefined;
    let closed = false;
    let retry;
    setStartError(null);
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
          setEvaluation(message.evaluation);
          append({ role: "tutor", kind: message.message.chat.kind, text: message.message.chat.text });
          setMarked({ highlights: message.message.meta?.highlights ?? [], board: boardRef.current });
        } else if (message.type === "error") handleError(ws, message);
      };
      ws.onclose = () => {
        setConnected(false);
        setThinking(false);
        if (!closed) retry = setTimeout(open, RECONNECT_MS);
      };
    };

    const handleError = (ws, message) => {
      if (message.code === "no_session") {
        // The server lost the session (e.g. it restarted): start again and repeat the message once.
        startSession(ws);
        const request = pending.current;
        if (request && !request.replayed) {
          pending.current = { ...request, replayed: true };
          sendRequest(ws, request.learner_text);
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
      sendRequest(ws, text.trim());
      return true;
    },
    [append, sendRequest],
  );

  const highlights = liveHighlights(marked.highlights, marked.board, board);
  return { connected, thinking, evaluation, startError, highlights, send };
}
