import React, { useEffect, useState, useCallback } from "react";
import { fetchSessions, fetchTasks } from "../services/api";
import type { Session, Task } from "../types";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-900 text-yellow-300",
  executing: "bg-blue-900 text-blue-300",
  escalated: "bg-orange-900 text-orange-300",
  completed: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

const SessionViewer: React.FC = () => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<Session | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSessions();
      setSessions(s);
    } catch {
      setError("Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSessions(); }, []);

  const handleSelect = async (session: Session) => {
    setSelected(session);
    setTasksLoading(true);
    try {
      const t = await fetchTasks(session.id);
      setTasks(t);
    } catch {
      setTasks([]);
    } finally {
      setTasksLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="bg-gray-900 rounded-lg border border-gray-800 md:col-span-1">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h2 className="font-semibold">Sessions</h2>
          <button onClick={loadSessions} className="text-xs text-gray-500 hover:text-gray-300">↻</button>
        </div>
        {loading && <p className="text-sm text-gray-500 p-4">Loading…</p>}
        {error && <p className="text-sm text-red-400 p-4">{error}</p>}
        {!loading && sessions.length === 0 && (
          <p className="text-sm text-gray-500 p-4">No sessions yet.</p>
        )}
        <ul className="divide-y divide-gray-800">
          {sessions.map((s) => (
            <li
              key={s.id}
              onClick={() => handleSelect(s)}
              className={`px-4 py-3 cursor-pointer transition-colors ${
                selected?.id === s.id ? "bg-blue-950 border-l-2 border-blue-500" : "hover:bg-gray-800"
              }`}
            >
              <p className="text-sm font-medium text-white">{s.title}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {s.id.slice(0, 8)}… · {new Date(s.created_at).toLocaleDateString()}
              </p>
            </li>
          ))}
        </ul>
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 md:col-span-2">
        {!selected ? (
          <div className="flex items-center justify-center h-full min-h-48 text-gray-600 text-sm">
            Select a session to view its tasks
          </div>
        ) : (
          <>
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="font-semibold">{selected.title}</h2>
              <p className="text-xs text-gray-500 mt-0.5">ID: {selected.id}</p>
            </div>
            {tasksLoading && <p className="text-sm text-gray-500 p-4">Loading tasks…</p>}
            {!tasksLoading && tasks.length === 0 && (
              <p className="text-sm text-gray-500 p-4">No tasks in this session.</p>
            )}
            <ul className="divide-y divide-gray-800">
              {tasks.map((task) => (
                <li key={task.id} className="px-4 py-3 flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-sm text-white truncate">
                      {(task.payload?.description as string) || task.id}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {new Date(task.created_at).toLocaleString()}
                    </p>
                  </div>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${STATUS_COLORS[task.status] || "bg-gray-800 text-gray-300"}`}>
                    {task.status}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
};

export default SessionViewer;
