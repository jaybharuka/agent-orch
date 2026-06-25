"""Agent-related schemas."""
from typing import Annotated, Literal, NotRequired, TypedDict
from pydantic import BaseModel, Field

from app.memory.memory_manager import MemoryManager
from app.services.escalation_service import EscalationService


class Subtask(BaseModel):
    """A single unit of work within an execution plan."""
    id: str
    description: str
    assigned_agent: str
    dependencies: list[str] = Field(default_factory=list)
    status: Literal["pending", "in_progress", "complete", "failed"] = "pending"
    expected_output: str | None = None
    output: str | None = None
    error: str | None = None
    tool_calls: list[dict] = Field(default_factory=list)


class AgentState(TypedDict):
    """Shared state carried through the LangGraph workflow."""
    task_id: str
    session_id: str
    user_id: str
    original_task: str
    execution_plan: list[Subtask]
    current_subtask_index: int
    agent_outputs: dict[str, str]
    memory_context: list[str]
    confidence_score: float
    escalation_required: bool
    escalation_reason: NotRequired[str | None]
    escalation_trigger: NotRequired[str | None]
    reviewer_score: NotRequired[float | None]
    reviewer_feedback: NotRequired[str | None]
    retry_counts: NotRequired[dict[str, int]]
    retries: NotRequired[dict[str, int]]
    final_output: NotRequired[str | None]
    error: NotRequired[str | None]
    duration_ms: NotRequired[float | None]
    cost_usd: NotRequired[float | None]
    tags: NotRequired[list[str]]
    status: Literal[
        "planning",
        "executing",
        "reviewing",
        "escalated",
        "complete",
        "failed",
    ]
    # Non-serializable objects carried through LangGraph state.
    # The Annotated reducer preserves the existing value when a node does not
    # return it (so it is not overwritten by None). For production use with a
    # checkpointer that serializes state, prefer a contextvars.ContextVar instead.
    memory_manager: Annotated[MemoryManager | None, lambda x, y: y or x]
    escalation_service: Annotated[EscalationService | None, lambda x, y: y or x]
