import React, { useState, useEffect } from "react";
import TaskQueue from "./components/TaskQueue";
import SessionViewer from "./components/SessionViewer";
import ReviewPanel from "./components/ReviewPanel";
import MemoryBrowser from "./components/MemoryBrowser";
import { checkHealth } from "./services/api";
import type { HealthStatus } from "./services/api";

type Tab = "tasks" | "sessions" | "reviews" | "memory";

const TABS: { id: Tab; label: string }[] = [
  { id: "tasks", label: "Task Queue" },
  { id: "sessions", label: "Sessions" },
  { id: "reviews", label: "Review Queue" },
  { id: "memory", label: "Memory Browser" },
];

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("tasks");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    checkHealth()
      .then((h) => { setHealth(h); setBackendDown(false); })
      .catch(() => setBackendDown(true));
  }, []);

  const degraded = backendDown || (health && health.status !== "ok");

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {degraded && (
        <div className="bg-red-950 border-b border-red-800 px-6 py-2 flex items-center justify-between">
          <span className="text-sm text-red-300">
            {backendDown
              ? "⚠ Backend unreachable — is docker-compose up?"
              : `⚠ Some services degraded: ${Object.entries(health?.services ?? {})
                  .filter(([, v]) => v !== "ok")
                  .map(([k]) => k)
                  .join(", ")}`}
          </span>
          {health && (
            <span className="text-xs text-red-500 font-mono">
              {Object.entries(health.services)
                .map(([k, v]) => `${k}:${v}`)
                .join(" · ")}
            </span>
          )}
        </div>
      )}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-bold text-white tracking-tight">
            🤖 Agent Orchestration
          </h1>
          <span className="text-xs text-gray-500">LangGraph · FastAPI · React</span>
        </div>
      </header>

      <nav className="bg-gray-900 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-6 flex space-x-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-blue-500 text-blue-400"
                  : "border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-600"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-6 py-6">
        {activeTab === "tasks" && <TaskQueue />}
        {activeTab === "sessions" && <SessionViewer />}
        {activeTab === "reviews" && <ReviewPanel />}
        {activeTab === "memory" && <MemoryBrowser />}
      </main>
    </div>
  );
}

export default App;
