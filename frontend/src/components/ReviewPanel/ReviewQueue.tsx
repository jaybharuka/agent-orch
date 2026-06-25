import React, { useEffect, useState } from "react";
import { useReviews } from "../../hooks/useReviews";
import { useWebSocket } from "../../hooks/useWebSocket";
import ReviewDetail from "./ReviewDetail";
import type { ApprovalRequest, ApprovalSeverity, EscalationContext } from "../../types";

interface ReviewQueueProps {
  userId: string;
}

const severityBadgeClass = (severity: ApprovalSeverity): string => {
  switch (severity) {
    case "notify":
      return "bg-blue-100 text-blue-800";
    case "approve_action":
      return "bg-yellow-100 text-yellow-800";
    case "approve_plan":
      return "bg-orange-100 text-orange-800";
    case "take_over":
      return "bg-red-100 text-red-800";
    default:
      return "bg-gray-100 text-gray-800";
  }
};

const formatDuration = (createdAt: string): string => {
  const diff = Date.now() - new Date(createdAt).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
};

const ReviewQueue: React.FC<ReviewQueueProps> = ({ userId }: ReviewQueueProps) => {
  const { pending, loading, error, fetchPending, fetchDetail } = useReviews();
  const [selected, setSelected] = useState<EscalationContext | null>(null);
  const wsUrl = `${process.env.REACT_APP_WS_URL || "ws://localhost:8003"}/api/v1/ws/${userId}`;
  const socket = useWebSocket(wsUrl);

  useEffect(() => {
    fetchPending();
  }, [fetchPending]);

  useEffect(() => {
    if (!socket) return;
    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.event === "approval_required") {
          fetchPending();
        }
      } catch {
        // Ignore malformed messages
      }
    };
    socket.addEventListener("message", handleMessage);
    return () => {
      socket.removeEventListener("message", handleMessage);
    };
  }, [socket, fetchPending]);

  const handleSelect = async (request: ApprovalRequest) => {
    const detail = await fetchDetail(request.id);
    if (detail) {
      setSelected(detail);
    }
  };

  return (
    <div className="border rounded-lg bg-white p-4">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Review Queue</h2>
        {pending.length > 0 && (
          <span className="bg-red-600 text-white text-xs font-bold px-2 py-1 rounded-full">
            {pending.length}
          </span>
        )}
      </div>

      {loading && <p className="text-sm text-gray-500">Loading...</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {pending.length === 0 && !loading && !error && (
        <p className="text-sm text-gray-500">No pending approvals.</p>
      )}

      <ul className="space-y-2">
        {pending.map((request: ApprovalRequest) => (
          <li
            key={request.id}
            onClick={() => handleSelect(request)}
            className="border rounded-md p-3 cursor-pointer hover:bg-gray-50 transition"
          >
            <div className="flex justify-between items-start">
              <div>
                <div className="font-medium text-sm">
                  {request.context_snapshot.original_task as string ||
                    request.proposed_action}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  trigger: {request.trigger} | waiting: {formatDuration(request.created_at)}
                </div>
              </div>
              <span
                className={`text-xs font-semibold px-2 py-1 rounded ${severityBadgeClass(
                  request.severity
                )}`}
              >
                {request.severity}
              </span>
            </div>
          </li>
        ))}
      </ul>

      {selected && (
        <ReviewDetail
          context={selected}
          onClose={() => setSelected(null)}
          onResolved={() => {
            setSelected(null);
            fetchPending();
          }}
        />
      )}
    </div>
  );
};

export default ReviewQueue;
