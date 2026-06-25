"""Approval request service tests."""
import uuid
from datetime import datetime

import pytest

from app.models.approval_request import ApprovalRequest
from app.schemas.approval_request import ApprovalDecision
from app.services import approval_request_service


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


@pytest.mark.asyncio
async def test_create_approval_request_from_state_excludes_memory_manager():
    session = _FakeSession()
    state = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Test task",
        "memory_manager": object(),  # non-serializable object
        "execution_plan": [],
        "agent_outputs": {},
    }

    result = await approval_request_service.create_approval_request_from_state(
        db=session,
        task_id=uuid.UUID("12345678-1234-1234-1234-123456789abc"),
        session_id=uuid.UUID("22345678-1234-1234-1234-123456789abc"),
        user_id=uuid.UUID("32345678-1234-1234-1234-123456789abc"),
        trigger="low_confidence",
        severity="approve_plan",
        proposed_action="Wait for human review",
        agent_reasoning="Confidence below threshold",
        state=state,
        relevant_memories=[{"task_description": "past task"}],
    )

    assert session.committed
    assert len(session._requests) == 1
    request = session._requests[0]
    assert isinstance(request, ApprovalRequest)
    assert request.trigger == "low_confidence"
    assert request.severity == "approve_plan"
    snapshot = request.context_snapshot
    assert "memory_manager" not in snapshot
    assert snapshot["original_task"] == "Test task"
    assert result.status == "pending"


@pytest.mark.asyncio
async def test_get_approval_request():
    request_id = uuid.uuid4()
    request = ApprovalRequest(
        id=request_id,
        task_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trigger="low_reviewer_score",
        severity="take_over",
        status="pending",
        context_snapshot={},
        proposed_action="Take over",
        agent_reasoning="Retries exhausted",
    )
    session = _FakeSession(requests=[request])
    result = await approval_request_service.get_approval_request(session, request_id)
    assert result is not None
    assert result.id == request_id


@pytest.mark.asyncio
async def test_list_pending_approval_requests_filters_by_user():
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
        proposed_action="Approve action",
        agent_reasoning="Sensitive",
    )
    session = _FakeSession(requests=[request])
    results = await approval_request_service.list_pending_approval_requests(session, user_id)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_submit_approval_decision_updates_request():
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
    session = _FakeSession(requests=[request])
    decision = ApprovalDecision(
        decision="approve",
        notes="Looks good",
        reviewer_user_id=uuid.uuid4(),
    )
    result = await approval_request_service.submit_approval_decision(session, request_id, decision)
    assert session.committed
    assert result.status == "approve"
    assert result.reviewer_notes == "Looks good"
