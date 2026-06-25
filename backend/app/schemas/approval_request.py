"""Approval request Pydantic schemas."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class ApprovalRequestCreate(BaseModel):
    """Payload for creating an approval request in the queue."""

    task_id: UUID
    session_id: UUID
    user_id: UUID
    trigger: Literal[
        "low_confidence",
        "repeated_failure",
        "sensitive_operation",
        "low_reviewer_score",
        "user_requested",
    ]
    severity: Literal[
        "notify",
        "approve_action",
        "approve_plan",
        "take_over",
    ]
    context_snapshot: dict = Field(
        ..., description="Full AgentState snapshot; memory_manager must be excluded"
    )
    proposed_action: str = Field(..., description="What the agent wants to do next")
    agent_reasoning: str = Field(..., description="Why the agent escalated")
    relevant_memories: list[dict] | None = None


class ApprovalRequestRead(BaseModel):
    """Serialized approval request for the API and UI."""

    id: UUID
    task_id: UUID
    session_id: UUID
    user_id: UUID
    trigger: str
    severity: str
    status: str
    context_snapshot: dict
    proposed_action: str
    agent_reasoning: str
    relevant_memories: list[dict] | None
    reviewer_user_id: UUID | None
    reviewer_decision: str | None
    reviewer_notes: str | None
    modified_plan: list[dict] | None
    created_at: datetime
    updated_at: datetime | None
    resolved_at: datetime | None

    class Config:
        from_attributes = True


class ApprovalDecision(BaseModel):
    """Payload for a reviewer resolving an approval request."""

    decision: Literal["approve", "reject", "take_over"]
    notes: str | None = None
    modified_plan: list[dict] | None = Field(
        None, description="Reviewer-edited plan, required when taking over"
    )
    reviewer_user_id: UUID | None = None


class EscalationContext(BaseModel):
    """Everything the UI needs to display for a single escalation."""

    approval_request: ApprovalRequestRead
    proposed_action: str
    agent_reasoning: str
    context_snapshot: dict
    relevant_memories: list[dict]
    can_take_over: bool = True
    can_edit_plan: bool = True
