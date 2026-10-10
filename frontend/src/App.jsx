import { useEffect, useState } from "react";

// Scaffold only: shows that the frontend reaches the backend through the dev proxy.
export default function App() {
  const [backend, setBackend] = useState("checking");

  useEffect(() => {
    fetch("/api/health")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((body) => setBackend(body.status === "ok" ? "connected" : "unexpected reply"))
      .catch(() => setBackend("unreachable"));
  }, []);

  return (
    <main className="app">
      <h1>Schematics AI Tutor</h1>
      <p>
        Backend: <span data-testid="backend-status">{backend}</span>
      </p>
    </main>
  );
}
