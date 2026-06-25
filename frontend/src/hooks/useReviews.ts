import { useState, useCallback } from "react";
import {
  fetchPendingReviews,
  fetchReviewDetail,
  submitReviewDecision,
  fetchChatMessages,
  sendChatMessage,
} from "../services/api";
import type {
  ApprovalRequest,
  ApprovalDecisionPayload,
  ChatMessage,
  EscalationContext,
} from "../types";

export const useReviews = () => {
  const [pending, setPending] = useState<ApprovalRequest[]>([]);
  const [detail, setDetail] = useState<EscalationContext | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPending = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPendingReviews();
      setPending(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch reviews");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchDetail = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchReviewDetail(id);
      setDetail(data);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch detail");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const submitDecision = useCallback(
    async (id: string, payload: ApprovalDecisionPayload) => {
      setLoading(true);
      setError(null);
      try {
        const updated = await submitReviewDecision(id, payload);
        setPending((prev: ApprovalRequest[]) => prev.filter((r) => r.id !== id));
        setDetail((prev: EscalationContext | null) =>
          prev ? { ...prev, approval_request: updated } : prev
        );
        return updated;
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to submit decision"
        );
        throw err;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const loadChat = useCallback(async (id: string) => {
    try {
      const data = await fetchChatMessages(id);
      setMessages(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch chat");
    }
  }, []);

  const sendChat = useCallback(
    async (id: string, content: string, role: ChatMessage["role"]) => {
      try {
        const data = await sendChatMessage(id, { role, content });
        setMessages(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to send chat");
      }
    },
    []
  );

  return {
    pending,
    detail,
    messages,
    loading,
    error,
    fetchPending,
    fetchDetail,
    submitDecision,
    loadChat,
    sendChat,
  };
};
