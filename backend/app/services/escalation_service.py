"""Escalation service for human-in-the-loop approval queue."""
import json
import uuid
from typing import Any
from uuid import UUID

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session
from app.memory.memory_manager import MemoryManager
from app.schemas.approval_request import ApprovalDecision, ApprovalRequestRead
from app.services.approval_request_service import (
    create_approval_request_from_state,
    get_approval_request,
    list_pending_approval_requests,
    submit_approval_decision,
)


TRIGGER_TO_SEVERITY: dict[str, str] = {
    "low_confidence": "approve_plan",
    "repeated_failure": "approve_action",
    "sensitive_operation": "approve_action",
    "low_reviewer_score": "approve_plan",
    "user_requested": "take_over",
}

REQUIRED_SUBTASK_FIELDS = {"id", "description", "assigned_agent"}


class EscalationService:
    """Routes agent escalations into the approval queue and publishes Redis events."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        redis_client: redis.Redis | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self._redis_client = redis_client
        self._db_session = db_session

    async def _get_redis(self) -> redis.Redis:
        if self._redis_client is None:
            self._redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis_client

    async def _publish(self, channel: str, message: dict) -> None:
        client = await self._get_redis()
        await client.publish(channel, json.dumps(message))

    @staticmethod
    def _snapshot_state(state: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON-safe copy of the AgentState without non-serializable objects."""
        snapshot = dict(state)
        snapshot.pop("memory_manager", None)
        snapshot.pop("escalation_service", None)
        for key, value in snapshot.items():
            if hasattr(value, "model_dump"):
                snapshot[key] = value.model_dump()
            elif hasattr(value, "dict"):
                snapshot[key] = value.dict()
        return snapshot

    @staticmethod
    def _to_uuid(value: Any) -> UUID:
        if isinstance(value, UUID):
            return value
        return UUID(str(value))

    async def escalate(
        self,
        state: dict[str, Any],
        trigger: str,
        proposed_action: str,
        agent_reasoning: str,
    ) -> ApprovalRequestRead:
        """Create an approval request from an escalation and notify reviewers."""
        severity = TRIGGER_TO_SEVERITY.get(trigger, "approve_action")
        task_id = self._to_uuid(state.get("task_id", uuid.uuid4()))
        session_id = self._to_uuid(state.get("session_id", uuid.uuid4()))
        user_id = self._to_uuid(state.get("user_id", uuid.uuid4()))

        memories = await self.memory_manager.list_memories(str(user_id))
        relevant_memories = [
            entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
            for entry in memories[:5]
        ]

        if self._db_session is not None:
            request = await create_approval_request_from_state(
                db=self._db_session,
                task_id=task_id,
                session_id=session_id,
                user_id=user_id,
                trigger=trigger,
                severity=severity,
                proposed_action=proposed_action,
                agent_reasoning=agent_reasoning,
                state=self._snapshot_state(state),
                relevant_memories=relevant_memories,
            )
        else:
            async with async_session() as db:
                request = await create_approval_request_from_state(
                    db=db,
                    task_id=task_id,
                    session_id=session_id,
                    user_id=user_id,
                    trigger=trigger,
                    severity=severity,
                    proposed_action=proposed_action,
                    agent_reasoning=agent_reasoning,
                    state=self._snapshot_state(state),
                    relevant_memories=relevant_memories,
                )

        await self._publish(
            f"approvals:{user_id}",
            {"event": "approval_required", "request_id": str(request.id)},
        )
        return request

    async def resolve(
        self,
        request_id: UUID,
        decision: ApprovalDecision,
        reviewer_user_id: UUID,
    ) -> ApprovalRequestRead:
        """Record a reviewer decision, validate any modified plan, and notify listeners."""
        if decision.modified_plan is not None:
            self._validate_plan(decision.modified_plan)

        payload = ApprovalDecision(
            decision=decision.decision,
            notes=decision.notes,
            modified_plan=decision.modified_plan,
            reviewer_user_id=reviewer_user_id,
        )

        if self._db_session is not None:
            resolved = await submit_approval_decision(
                db=self._db_session, request_id=request_id, payload=payload
            )
        else:
            async with async_session() as db:
                resolved = await submit_approval_decision(
                    db=db, request_id=request_id, payload=payload
                )

        await self._publish(
            f"approval_resolved:{request_id}",
            {
                "event": "approval_resolved",
                "request_id": str(request_id),
                "decision": decision.decision,
            },
        )
        return resolved

    async def get_pending(self, user_id: UUID) -> list[ApprovalRequestRead]:
        """List pending approval requests for a user."""
        if self._db_session is not None:
            return await list_pending_approval_requests(
                db=self._db_session, user_id=user_id
            )
        async with async_session() as db:
            return await list_pending_approval_requests(
                db=db, user_id=user_id
            )

    async def get_by_id(self, request_id: UUID) -> ApprovalRequestRead | None:
        """Fetch a single approval request."""
        if self._db_session is not None:
            return await get_approval_request(
                db=self._db_session, request_id=request_id
            )
        async with async_session() as db:
            return await get_approval_request(
                db=db, request_id=request_id
            )

    @staticmethod
    def _validate_plan(plan: list[dict]) -> None:
        """Ensure every subtask in a reviewer-edited plan has the required fields."""
        if not isinstance(plan, list):
            raise ValueError("modified_plan must be a list")
        for i, subtask in enumerate(plan):
            if not isinstance(subtask, dict):
                raise ValueError(f"subtask {i} must be a dict")
            missing = REQUIRED_SUBTASK_FIELDS - subtask.keys()
            if missing:
                raise ValueError(f"subtask {i} missing fields: {sorted(missing)}")
