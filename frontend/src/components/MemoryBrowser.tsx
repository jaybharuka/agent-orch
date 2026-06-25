import React, { useState } from "react";
import { queryMemory } from "../services/api";

interface MemoryResult {
  id: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

const MemoryBrowser: React.FC = () => {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<MemoryResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      const data = await queryMemory(query.trim(), topK);
      setResults(data);
    } catch {
      setError("Failed to query memory");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-sm font-semibold text-gray-400 uppercase mb-3">Query Vector Memory</h2>
        <div className="flex gap-2">
          <input
            className="flex-1 bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:outline-none focus:border-blue-500"
            placeholder="Search for similar tasks or memories…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
          <select
            className="bg-gray-800 text-white text-sm rounded px-3 py-2 border border-gray-700 focus:outline-none focus:border-blue-500"
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
          >
            {[3, 5, 10, 20].map((n) => (
              <option key={n} value={n}>Top {n}</option>
            ))}
          </select>
          <button
            onClick={handleSearch}
            disabled={loading || !query.trim()}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-medium px-4 py-2 rounded transition-colors"
          >
            {loading ? "…" : "Search"}
          </button>
        </div>
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800">
        <div className="px-4 py-3 border-b border-gray-800">
          <h2 className="font-semibold">Results</h2>
        </div>
        {error && <p className="text-sm text-red-400 p-4">{error}</p>}
        {!searched && (
          <p className="text-sm text-gray-500 p-4">Run a search to retrieve relevant memories from ChromaDB.</p>
        )}
        {searched && !loading && results.length === 0 && (
          <p className="text-sm text-gray-500 p-4">No memories found. The vector store may be empty — tasks need to be run first to populate it.</p>
        )}
        <ul className="divide-y divide-gray-800">
          {results.map((r) => (
            <li key={r.id} className="px-4 py-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-500 font-mono">{r.id.slice(0, 12)}…</span>
                <span className="text-xs font-semibold text-blue-400">
                  score: {r.score.toFixed(3)}
                </span>
              </div>
              <p className="text-sm text-white">{r.content}</p>
              {Object.keys(r.metadata).length > 0 && (
                <pre className="text-xs text-gray-500 mt-1 overflow-x-auto">
                  {JSON.stringify(r.metadata, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default MemoryBrowser;
