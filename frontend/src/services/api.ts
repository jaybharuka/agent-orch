import axios from "axios";
import type {
  ApprovalDecisionPayload,
  ApprovalRequest,
  ChatMessage,
  EscalationContext,
  Task,
  Session,
} from "../types";

const BASE_URL = process.env.REACT_APP_API_URL ?? "http://localhost:8003";
const API_URL = `${BASE_URL}/api/v1`;

const api = axios.create({
  baseURL: API_URL,
  timeout: 10_000,
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error("[API]", err.config?.url, err.message);
    return Promise.reject(err);
  }
);

export interface HealthStatus {
  status: "ok" | "degraded";
  version: string;
  services: { redis: string; postgres: string; chroma: string };
}

export const checkHealth = async (): Promise<HealthStatus> => {
  const response = await axios.get<HealthStatus>(`${BASE_URL}/health`, { timeout: 5_000 });
  return response.data;
};

export const fetchTasks = async (sessionId?: string): Promise<Task[]> => {
  const response = await api.get("/tasks/", { params: sessionId ? { session_id: sessionId } : {} });
  return response.data;
};

export const createTask = async (sessionId: string, payload: Record<string, unknown>): Promise<Task> => {
  const response = await api.post("/tasks/", { session_id: sessionId, payload });
  return response.data;
};

export const escalateTask = async (taskId: string): Promise<void> => {
  await api.post(`/tasks/${taskId}/escalate`);
};

export const fetchSessions = async (): Promise<Session[]> => {
  const response = await api.get("/sessions/");
  return response.data;
};

export const createSession = async (title: string): Promise<Session> => {
  const response = await api.post("/sessions/", { title, context: {} });
  return response.data;
};

export const queryMemory = async (query: string, topK = 5): Promise<Array<{id: string; content: string; score: number; metadata: Record<string, unknown>}>> => {
  const response = await api.post("/memory/query", { query, top_k: topK });
  return response.data;
};

export const fetchPendingReviews = async (): Promise<ApprovalRequest[]> => {
  const response = await api.get("/reviews/pending");
  return response.data;
};

export const fetchReviewDetail = async (
  requestId: string
): Promise<EscalationContext> => {
  const response = await api.get(`/reviews/${requestId}`);
  return response.data;
};

export const submitReviewDecision = async (
  requestId: string,
  payload: ApprovalDecisionPayload
): Promise<ApprovalRequest> => {
  const response = await api.post(`/reviews/${requestId}/decide`, payload);
  return response.data;
};

export const fetchChatMessages = async (
  requestId: string
): Promise<ChatMessage[]> => {
  const response = await api.get(`/reviews/${requestId}/chat`);
  return response.data;
};

export const sendChatMessage = async (
  requestId: string,
  message: Omit<ChatMessage, "timestamp">
): Promise<ChatMessage[]> => {
  const response = await api.post(`/reviews/${requestId}/chat`, message);
  return response.data;
};
