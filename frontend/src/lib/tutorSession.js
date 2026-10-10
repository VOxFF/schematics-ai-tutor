// WebSocket session with the backend (docs/contract.md §1): session.start, tutor.request.
import { useCallback, useEffect, useRef, useState } from "react";

const RECONNECT_MS = 2000;

function socketUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/session`;
}

// level: the current Level (or null); chat: [{role, text, kind?}]; onChat: (nextChat) => void
export function useTutorSession(level, chat, onChat) {
  const [connected, setConnected] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const socket = useRef(null);
  const chatRef = useRef(chat);
  chatRef.current = chat;

  const append = useCallback((entry) => onChat([...chatRef.current, entry]), [onChat]);

  useEffect(() => {
    if (!level) return undefined;
    let closed = false;
    let retry;

    const open = () => {
      const ws = new WebSocket(socketUrl());
      socket.current = ws;
      ws.onopen = () => {
        setConnected(true);
        const history = chatRef.current.filter((m) => m.role !== "error").map(({ role, text }) => ({ role, text }));
        ws.send(JSON.stringify({ type: "session.start", level, history }));
      };
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "evaluation") setEvaluation(message.evaluation);
        else if (message.type === "tutor.started") setThinking(true);
        else if (message.type === "tutor.message") {
          setThinking(false);
          setEvaluation(message.evaluation);
          append({ role: "tutor", kind: message.message.chat.kind, text: message.message.chat.text });
        } else if (message.type === "error") {
          setThinking(false);
          if (message.request_id) append({ role: "error", text: message.message });
        }
      };
      ws.onclose = () => {
        setConnected(false);
        setThinking(false);
        if (!closed) retry = setTimeout(open, RECONNECT_MS);
      };
    };

    open();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
    // Reconnect only when the task changes, not on every chat update.
  }, [level?.id]);

  const send = useCallback(
    (text) => {
      const ws = socket.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !text.trim()) return false;
      append({ role: "learner", text: text.trim() });
      ws.send(JSON.stringify({ type: "tutor.request", request_id: crypto.randomUUID(), action: "message", learner_text: text.trim() }));
      return true;
    },
    [append],
  );

  return { connected, thinking, evaluation, send };
}
