export interface Task {
  id: string;
  session_id: string;
  status: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
}

export interface Session {
  id: string;
  title: string;
  context: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
}

export interface Review {
  id: string;
  task_id: string;
  status: string;
  feedback: string | null;
  approved: boolean | null;
  created_at: string;
  resolved_at: string | null;
}

export type ApprovalTrigger =
  | "low_confidence"
  | "repeated_failure"
  | "sensitive_operation"
  | "low_reviewer_score"
  | "user_requested";

export type ApprovalSeverity =
  | "notify"
  | "approve_action"
  | "approve_plan"
  | "take_over";

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "taken_over";

export interface RelevantMemory {
  id: string;
  task_description: string;
  summary: string;
  reviewer_score: number;
  tags: string[];
  importance_score?: number;
}

export interface ApprovalRequest {
  id: string;
  task_id: string;
  session_id: string;
  user_id: string;
  trigger: ApprovalTrigger;
  severity: ApprovalSeverity;
  status: ApprovalStatus;
  context_snapshot: Record<string, unknown>;
  proposed_action: string;
  agent_reasoning: string;
  relevant_memories: RelevantMemory[] | null;
  reviewer_user_id: string | null;
  reviewer_decision: string | null;
  reviewer_notes: string | null;
  modified_plan: Array<Record<string, unknown>> | null;
  created_at: string;
  updated_at: string | null;
  resolved_at: string | null;
}

export interface EscalationContext {
  approval_request: ApprovalRequest;
  proposed_action: string;
  agent_reasoning: string;
  context_snapshot: Record<string, unknown>;
  relevant_memories: RelevantMemory[];
  can_take_over: boolean;
  can_edit_plan: boolean;
}

export interface ChatMessage {
  role: "human" | "agent";
  content: string;
  timestamp: string;
}

export interface ApprovalDecisionPayload {
  decision: "approve" | "reject" | "take_over";
  notes?: string;
  modified_plan?: Array<Record<string, unknown>>;
}
