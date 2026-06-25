import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { fetchTasks, fetchSessions, createSession, createTask, escalateTask } from "../services/api";
import type { Task, Session } from "../types";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-900 text-yellow-300",
  executing: "bg-blue-900 text-blue-300",
  escalated: "bg-orange-900 text-orange-300",
  completed: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

const TaskQueue: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<string>("");
  const [newSessionTitle, setNewSessionTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendUnreachable, setBackendUnreachable] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setBackendUnreachable(false);
    try {
      const [t, s] = await Promise.all([fetchTasks(), fetchSessions()]);
      setTasks(t);
      setSessions(s);
      if (s.length > 0 && !selectedSession) setSelectedSession(s[0].id);
    } catch (err) {
      if (axios.isAxiosError(err) && !err.response) {
        setBackendUnreachable(true);
        setError("Backend unreachable — is Docker running?");
      } else {
        setError("Failed to load data");
      }
    } finally {
      setLoading(false);
    }
  }, [selectedSession]);

  useEffect(() => { loadData(); }, []);

  const handleCreateSession = async () => {
    if (!newSessionTitle.trim()) return;
    try {
      const s = await createSession(newSessionTitle.trim());
      setSessions((prev) => [s, ...prev]);
      setSelectedSession(s.id);
      setNewSessionTitle("");
    } catch {
      setError("Failed to create session");
    }
  };

  const handleCreateTask = async () => {
    if (!selectedSession || !taskDescription.trim()) return;
    try {
      const t = await createTask(selectedSession, { description: taskDescription.trim() });
      setTasks((prev) => [t, ...prev]);
      setTaskDescription("");
    } catch {
      setError("Failed to create task");
    }
  };

  const handleEscalate = async (taskId: string) => {
    try {
      await escalateTask(taskId);
    } catch {
      setError("Failed to escalate task");
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
          <h2 className="text-sm font-semibold text-gray-400 uppercase mb-3">New Session</h2>
          <div className="flex gap-2">
            <input
              className="flex-1 bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:outline-none focus:border-blue-500"
              placeholder="Session title…"
              value={newSessionTitle}
              onChange={(e) => setNewSessionTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreateSession()}
            />
            <button
              onClick={handleCreateSession}
              className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded transition-colors"
            >
              Create
            </button>
          </div>
        </div>

        <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
          <h2 className="text-sm font-semibold text-gray-400 uppercase mb-3">New Task</h2>
          <div className="space-y-2">
            <select
              className="w-full bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:outline-none focus:border-blue-500"
              value={selectedSession}
              onChange={(e) => setSelectedSession(e.target.value)}
            >
              {sessions.length === 0 && <option value="">— create a session first —</option>}
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>{s.title}</option>
              ))}
            </select>
            <div className="flex gap-2">
              <input
                className="flex-1 bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:outline-none focus:border-blue-500"
                placeholder="Describe the task…"
                value={taskDescription}
                onChange={(e) => setTaskDescription(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateTask()}
              />
              <button
                onClick={handleCreateTask}
                disabled={!selectedSession}
                className="bg-green-600 hover:bg-green-500 disabled:opacity-40 text-white text-sm font-medium px-4 py-2 rounded transition-colors"
              >
                Add
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h2 className="font-semibold">All Tasks</h2>
          <button onClick={loadData} className="text-xs text-gray-500 hover:text-gray-300 transition-colors">
            ↻ Refresh
          </button>
        </div>
        {loading && <p className="text-sm text-gray-500 p-4">Loading…</p>}
        {error && (
          <div className="p-4 flex items-center gap-3">
            <p className="text-sm text-red-400 flex-1">{error}</p>
            <button
              onClick={loadData}
              className="text-xs text-red-300 border border-red-700 hover:border-red-500 hover:text-red-200 px-3 py-1 rounded transition-colors shrink-0"
            >
              {backendUnreachable ? "Retry" : "↻ Retry"}
            </button>
          </div>
        )}
        {!loading && !error && tasks.length === 0 && (
          <p className="text-sm text-gray-500 p-4">No tasks yet. Create a session and add a task above.</p>
        )}
        <ul className="divide-y divide-gray-800">
          {tasks.map((task) => (
            <li key={task.id} className="px-4 py-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm text-white truncate">
                  {(task.payload?.description as string) || task.id}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {task.id.slice(0, 8)}… · {new Date(task.created_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_COLORS[task.status] || "bg-gray-800 text-gray-300"}`}>
                  {task.status}
                </span>
                {task.status === "executing" && (
                  <button
                    onClick={() => handleEscalate(task.id)}
                    className="text-xs text-orange-400 hover:text-orange-300 border border-orange-800 hover:border-orange-600 px-2 py-0.5 rounded transition-colors"
                  >
                    Escalate
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default TaskQueue;
