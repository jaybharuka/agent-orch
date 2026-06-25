"""EscalationService tests."""
import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from pydantic import BaseModel

from app.models.approval_request import ApprovalRequest
from app.schemas.approval_request import ApprovalDecision, ApprovalRequestRead
from app.services import escalation_service
from app.services.escalation_service import EscalationService


class _FakeMemoryEntry(BaseModel):
    id: str = "mem-1"
    task_description: str = "Past task"
    summary: str = "Past summary"
    tools_used: list[str] = ["web_search"]
    reviewer_score: float = 0.8
    created_at: str = "2024-01-01T00:00:00"
    tags: list[str] = ["ai"]
    importance_score: float = 0.7


class _FakeMemoryManager:
    def __init__(self, memories=None):
        self.memories = memories or [_FakeMemoryEntry()]

    async def list_memories(self, user_id: str) -> list:
        return self.memories


class _FakeRedis:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class _FakeResult:
    def __init__(self, data=None):
        self._data = data or []

    def scalars(self):
        return self

    def all(self):
        return self._data

    def scalar_one_or_none(self):
        return self._data[0] if self._data else None


class _FakeSession:
    """In-memory fake async session that applies simple UPDATE statements."""

    def __init__(self, requests=None):
        self._requests = list(requests or [])
        self.committed = False

    def add(self, obj):
        self._requests.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()
        if not getattr(obj, "created_at", None):
            obj.created_at = datetime.utcnow()

    async def execute(self, query):
        cls_name = query.__class__.__name__
        if cls_name == "Update":
            values = self._extract_values(query)
            for obj in self._requests:
                if self._matches(obj, query):
                    for attr, value in values.items():
                        if callable(value):
                            value = datetime.utcnow()
                        setattr(obj, attr, value)
            return _FakeResult([])
        return _FakeResult(self._requests)

    def _matches(self, obj, query):
        where = getattr(query, "whereclause", None)
        if where is None:
            return True
        where_str = str(where)
        return str(getattr(obj, "id", None)) in where_str

    def _extract_values(self, query):
        values = {}
        raw = getattr(query, "_values", {}) or {}
        for col, value in raw.items():
            attr = col.name if hasattr(col, "name") else str(col)
            values[attr] = value
        return values


@pytest.fixture
def service():
    return EscalationService(
        memory_manager=_FakeMemoryManager(),
        redis_client=_FakeRedis(),
        db_session=_FakeSession(),
    )


@pytest.mark.asyncio
async def test_escalate_maps_trigger_to_severity_and_publishes(service):
    state = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Test task",
        "memory_manager": object(),
        "execution_plan": [],
        "agent_outputs": {},
    }

    request = await service.escalate(
        state=state,
        trigger="low_confidence",
        proposed_action="Wait for human review",
        agent_reasoning="Confidence below threshold",
    )

    assert isinstance(request, ApprovalRequestRead)
    assert request.trigger == "low_confidence"
    assert request.severity == "approve_plan"
    assert request.status == "pending"
    assert "memory_manager" not in request.context_snapshot
    assert request.relevant_memories is not None
    assert len(request.relevant_memories) == 1
    assert service._redis_client.published
    channel, message = service._redis_client.published[0]
    assert channel == "approvals:user-1"
    data = json.loads(message)
    assert data["event"] == "approval_required"
    assert data["request_id"] == str(request.id)


@pytest.mark.asyncio
async def test_escalate_user_requested_maps_to_take_over(service):
    state = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Test task",
        "memory_manager": object(),
    }
    request = await service.escalate(
        state=state,
        trigger="user_requested",
        proposed_action="Take over",
        agent_reasoning="User asked for human control",
    )
    assert request.severity == "take_over"


@pytest.mark.asyncio
async def test_resolve_updates_and_publishes(service):
    request_id = uuid.uuid4()
    request = ApprovalRequest(
        id=request_id,
        task_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trigger="low_confidence",
        severity="approve_plan",
        status="pending",
        context_snapshot={},
        proposed_action="Wait",
        agent_reasoning="Low confidence",
    )
    service._db_session._requests = [request]

    reviewer_id = uuid.uuid4()
    decision = ApprovalDecision(decision="approve", notes="Looks good")
    resolved = await service.resolve(
        request_id=request_id, decision=decision, reviewer_user_id=reviewer_id
    )

    assert resolved.status == "approve"
    assert resolved.reviewer_notes == "Looks good"
    assert service._db_session.committed
    assert service._redis_client.published
    channel, message = service._redis_client.published[0]
    assert channel == f"approval_resolved:{request_id}"
    data = json.loads(message)
    assert data["event"] == "approval_resolved"


@pytest.mark.asyncio
async def test_resolve_rejects_invalid_modified_plan(service):
    request_id = uuid.uuid4()
    decision = ApprovalDecision(
        decision="take_over",
        modified_plan=[{"description": "missing fields"}],
    )
    with pytest.raises(ValueError, match="missing fields"):
        await service.resolve(request_id=request_id, decision=decision, reviewer_user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_resolve_accepts_valid_modified_plan(service):
    request_id = uuid.uuid4()
    request = ApprovalRequest(
        id=request_id,
        task_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trigger="low_confidence",
        severity="approve_plan",
        status="pending",
        context_snapshot={},
        proposed_action="Wait",
        agent_reasoning="Low confidence",
    )
    service._db_session._requests = [request]

    decision = ApprovalDecision(
        decision="take_over",
        modified_plan=[{"id": "1", "description": "Search", "assigned_agent": "research"}],
    )
    resolved = await service.resolve(
        request_id=request_id, decision=decision, reviewer_user_id=uuid.uuid4()
    )
    assert resolved.status == "take_over"


@pytest.mark.asyncio
async def test_get_pending_and_get_by_id(service):
    user_id = uuid.uuid4()
    request = ApprovalRequest(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=user_id,
        trigger="sensitive_operation",
        severity="approve_action",
        status="pending",
        context_snapshot={},
        proposed_action="Approve",
        agent_reasoning="Sensitive",
    )
    service._db_session._requests = [request]

    pending = await service.get_pending(user_id)
    assert len(pending) == 1
    assert pending[0].status == "pending"

    found = await service.get_by_id(request.id)
    assert found is not None
    assert found.id == request.id
