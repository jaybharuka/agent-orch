import React, { useState } from "react";
import { useReviews } from "../../hooks/useReviews";
import ChatPanel from "./ChatPanel";
import type {
  ApprovalDecisionPayload,
  ApprovalRequest,
  ApprovalSeverity,
  EscalationContext,
  RelevantMemory,
} from "../../types";

interface ReviewDetailProps {
  context: EscalationContext;
  onClose: () => void;
  onResolved: () => void;
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

const ReviewDetail: React.FC<ReviewDetailProps> = ({
  context,
  onClose,
  onResolved,
}: ReviewDetailProps) => {
  const { submitDecision } = useReviews();
  const [notes, setNotes] = useState("");
  const [editedPlan, setEditedPlan] = useState<string>(
    JSON.stringify(
      context.approval_request.modified_plan ||
        context.context_snapshot.execution_plan ||
        [],
      null,
      2
    )
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const request = context.approval_request;
  const plan = context.context_snapshot.execution_plan as Array<
    Record<string, unknown>
  >;

  const handleDecision = async (decision: ApprovalDecisionPayload["decision"]) => {
    setSubmitting(true);
    setError(null);
    try {
      const payload: ApprovalDecisionPayload = {
        decision,
        notes,
      };
      if (context.can_edit_plan && decision === "approve") {
        try {
          payload.modified_plan = JSON.parse(editedPlan);
        } catch {
          setError("Modified plan is not valid JSON");
          setSubmitting(false);
          return;
        }
      }
      await submitDecision(request.id, payload);
      onResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="p-4 border-b flex justify-between items-center">
          <div>
            <h2 className="text-lg font-semibold">Review Escalation</h2>
            <span
              className={`inline-block px-2 py-1 rounded text-xs font-semibold mt-1 ${severityBadgeClass(
                request.severity
              )}`}
            >
              {request.severity}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 text-xl"
          >
            &times;
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Left panel: task context */}
          <div className="space-y-4">
            <div className="border rounded-lg p-3 bg-gray-50">
              <h3 className="font-semibold text-sm mb-2">Original Task</h3>
              <p className="text-sm text-gray-800">
                {(context.context_snapshot.original_task as string) ||
                  request.proposed_action}
              </p>
            </div>

            <div className="border rounded-lg p-3 bg-gray-50">
              <h3 className="font-semibold text-sm mb-2">Execution Plan</h3>
              {plan && plan.length > 0 ? (
                <ul className="space-y-2 text-sm">
                  {plan.map((subtask, idx) => (
                    <li key={idx} className="border-l-4 border-gray-300 pl-2">
                      <div className="font-medium">{String(subtask.id)}</div>
                      <div className="text-gray-600">
                        {String(subtask.description)}
                      </div>
                      <div className="text-xs text-gray-500">
                        status: {String(subtask.status || "pending")} | agent: {String(subtask.assigned_agent)}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-500">No plan available.</p>
              )}
            </div>

            <div className="border rounded-lg p-3 bg-gray-50">
              <h3 className="font-semibold text-sm mb-2">Agent Reasoning</h3>
              <p className="text-sm text-gray-800">{request.agent_reasoning}</p>
            </div>

            <div className="border rounded-lg p-3 bg-gray-50">
              <h3 className="font-semibold text-sm mb-2">Proposed Action</h3>
              <p className="text-sm text-gray-800">{request.proposed_action}</p>
            </div>
          </div>

          {/* Middle panel: relevant memories */}
          <div className="border rounded-lg p-3 bg-gray-50">
            <h3 className="font-semibold text-sm mb-2">Relevant Memories</h3>
            {context.relevant_memories.length > 0 ? (
              <ul className="space-y-3">
                {context.relevant_memories.map((memory: RelevantMemory) => (
                  <li key={memory.id} className="bg-white p-3 rounded border text-sm">
                    <div className="font-medium">{memory.task_description}</div>
                    <div className="text-gray-600">{memory.summary}</div>
                    <div className="text-xs text-gray-500 mt-1">
                      score: {memory.reviewer_score} | tags: {memory.tags.join(", ")}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500">No relevant memories.</p>
            )}
          </div>

          {/* Right panel: decision */}
          <div className="space-y-4">
            {context.can_edit_plan && request.severity === "approve_plan" && (
              <div className="border rounded-lg p-3 bg-gray-50">
                <h3 className="font-semibold text-sm mb-2">Edit Plan</h3>
                <textarea
                  value={editedPlan}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                    setEditedPlan(e.target.value)
                  }
                  rows={10}
                  className="w-full border rounded-md p-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            )}

            <div className="border rounded-lg p-3 bg-gray-50">
              <h3 className="font-semibold text-sm mb-2">Notes</h3>
              <textarea
                value={notes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  setNotes(e.target.value)
                }
                rows={4}
                placeholder="Reviewer notes..."
                className="w-full border rounded-md p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => handleDecision("approve")}
                disabled={submitting}
                className="px-4 py-2 bg-green-600 text-white rounded-md text-sm hover:bg-green-700 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                onClick={() => handleDecision("reject")}
                disabled={submitting}
                className="px-4 py-2 bg-red-600 text-white rounded-md text-sm hover:bg-red-700 disabled:opacity-50"
              >
                Reject
              </button>
              {request.severity === "take_over" && (
                <button
                  onClick={() => handleDecision("take_over")}
                  disabled={submitting}
                  className="px-4 py-2 bg-purple-600 text-white rounded-md text-sm hover:bg-purple-700 disabled:opacity-50"
                >
                  Take Over
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="p-4 border-t">
          <ChatPanel requestId={request.id} />
        </div>
      </div>
    </div>
  );
};

export default ReviewDetail;
