"""Approval request business logic."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_request import ApprovalRequest
from app.schemas.approval_request import ApprovalDecision, ApprovalRequestCreate, ApprovalRequestRead


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of the AgentState without the memory_manager object."""
    snapshot = dict(state)
    snapshot.pop("memory_manager", None)
    # Pydantic models are converted to dicts; non-serializable objects are dropped.
    for key, value in snapshot.items():
        if hasattr(value, "model_dump"):
            snapshot[key] = value.model_dump()
        elif hasattr(value, "dict"):
            snapshot[key] = value.dict()
    return snapshot


async def create_approval_request(
    db: AsyncSession, payload: ApprovalRequestCreate
) -> ApprovalRequestRead:
    """Persist a new approval request from an escalation event."""
    request = ApprovalRequest(
        task_id=payload.task_id,
        session_id=payload.session_id,
        user_id=payload.user_id,
        trigger=payload.trigger,
        severity=payload.severity,
        status="pending",
        context_snapshot=payload.context_snapshot,
        proposed_action=payload.proposed_action,
        agent_reasoning=payload.agent_reasoning,
        relevant_memories=payload.relevant_memories,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    return ApprovalRequestRead.model_validate(request)


async def create_approval_request_from_state(
    db: AsyncSession,
    task_id: UUID,
    session_id: UUID,
    user_id: UUID,
    trigger: str,
    severity: str,
    proposed_action: str,
    agent_reasoning: str,
    state: dict[str, Any],
    relevant_memories: list[dict] | None = None,
) -> ApprovalRequestRead:
    """Convenience helper that builds a snapshot from a raw AgentState dict."""
    payload = ApprovalRequestCreate(
        task_id=task_id,
        session_id=session_id,
        user_id=user_id,
        trigger=trigger,
        severity=severity,
        context_snapshot=_serialize_state(state),
        proposed_action=proposed_action,
        agent_reasoning=agent_reasoning,
        relevant_memories=relevant_memories,
    )
    return await create_approval_request(db, payload)


async def get_approval_request(db: AsyncSession, request_id: UUID) -> ApprovalRequestRead | None:
    """Fetch a single approval request."""
    result = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == request_id))
    request = result.scalar_one_or_none()
    return ApprovalRequestRead.model_validate(request) if request else None


async def list_pending_approval_requests(
    db: AsyncSession, user_id: UUID | None = None
) -> list[ApprovalRequestRead]:
    """List pending approval requests, optionally filtered by user."""
    query = select(ApprovalRequest).where(ApprovalRequest.status == "pending")
    if user_id is not None:
        query = query.where(ApprovalRequest.user_id == user_id)
    result = await db.execute(query.order_by(ApprovalRequest.created_at.desc()))
    return [ApprovalRequestRead.model_validate(r) for r in result.scalars().all()]


_DECISION_TO_STATUS: dict[str, str] = {
    "approve": "approved",
    "reject": "rejected",
    "take_over": "taken_over",
}


async def submit_approval_decision(
    db: AsyncSession, request_id: UUID, payload: ApprovalDecision
) -> ApprovalRequestRead:
    """Record a reviewer decision and resolve the request."""
    resolved_at = datetime.now(timezone.utc)
    status = _DECISION_TO_STATUS.get(payload.decision, payload.decision)
    await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .values(
            status=status,
            reviewer_user_id=payload.reviewer_user_id,
            reviewer_decision=payload.decision,
            reviewer_notes=payload.notes,
            modified_plan=payload.modified_plan,
            resolved_at=resolved_at,
        )
    )
    await db.commit()
    return await get_approval_request(db, request_id)
