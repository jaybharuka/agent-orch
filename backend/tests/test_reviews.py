"""End-to-end tests for the review/escalation phase."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from app.agents.graph import _escalate_node
from app.agents.schemas import AgentState, Subtask


class _FakeMemoryManager:
    async def get_memory_context(self, task_id, user_id, query):
        from app.memory.memory_manager import MemoryContext
        return MemoryContext(similar_tasks=[], facts=[], working_outputs={})

    async def initialize_task(self, task_id, user_id, description, plan):
        pass

    async def save_specialist_output(self, task_id, subtask_id, output, tools_used):
        pass

    async def finalize_task(self, **kwargs):
        pass

    async def list_memories(self, user_id):
        return []


class _FakeApprovalRequest:
    def __init__(self, modified_plan=None):
        self.id = uuid.uuid4()
        self.modified_plan = modified_plan


def _base_state(**overrides) -> AgentState:
    state = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "test task",
        "execution_plan": [],
        "current_subtask_index": 0,
        "agent_outputs": {},
        "memory_context": [],
        "confidence_score": 0.9,
        "escalation_required": False,
        "escalation_reason": None,
        "escalation_trigger": None,
        "status": "executing",
        "memory_manager": None,
        "escalation_service": None,
        "retries": {},
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_supervisor_escalates_low_confidence(monkeypatch):
    monkeypatch.setattr("app.agents.publisher.publish_status", lambda *a, **k: None)

    from app.agents.supervisor import supervisor_node

    long_task = "x " * 100

    async def mock_generate_plan(self, task, task_id, user_id):
        return [Subtask(id="1", description="a", assigned_agent="research")]

    monkeypatch.setattr(
        "app.agents.supervisor.SupervisorAgent.generate_plan", mock_generate_plan
    )
    monkeypatch.setattr(
        "app.agents.supervisor.SupervisorAgent.compute_confidence",
        lambda *a, **k: 0.4,
    )

    state = _base_state(
        original_task=long_task,
        escalation_required=False,
        memory_manager=_FakeMemoryManager(),
    )
    node = supervisor_node()
    result = await node(state)
    assert result["escalation_required"] is True
    assert result["escalation_trigger"] == "low_confidence"
    assert result["status"] == "escalated"


@pytest.mark.asyncio
async def test_specialist_escalates_repeated_failure(monkeypatch):
    monkeypatch.setattr("app.agents.publisher.publish_status", lambda *a, **k: None)
    monkeypatch.setattr("app.memory.memory_manager.MemoryManager.get_memory_context", _FakeMemoryManager.get_memory_context)
    monkeypatch.setattr("app.memory.memory_manager.MemoryManager.save_specialist_output", _FakeMemoryManager.save_specialist_output)
    async def _fake_check_task_control(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.agents.specialist._check_task_control", _fake_check_task_control
    )

    from functools import partial
    from app.agents.specialist import specialist_node

    plan = [
        Subtask(id="1", description="a", assigned_agent="code"),
    ]
    retries = {"1": 2}
    outputs = {"1": {"status": "failed"}}
    state = _base_state(
        execution_plan=plan,
        current_subtask_index=0,
        agent_outputs=outputs,
        retries=retries,
        escalation_required=False,
    )
    result = await partial(specialist_node, agent_type="code")(state)
    assert result["escalation_required"] is True
    assert result["escalation_trigger"] == "repeated_failure"
    assert result["status"] == "escalated"


@pytest.mark.asyncio
async def test_specialist_escalates_sensitive_operation(monkeypatch):
    monkeypatch.setattr("app.agents.publisher.publish_status", lambda *a, **k: None)
    monkeypatch.setattr("app.memory.memory_manager.MemoryManager.get_memory_context", _FakeMemoryManager.get_memory_context)
    monkeypatch.setattr("app.memory.memory_manager.MemoryManager.save_specialist_output", _FakeMemoryManager.save_specialist_output)

    async def _fake_check_task_control(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.agents.specialist._check_task_control", _fake_check_task_control
    )

    from functools import partial
    from app.agents.specialist import specialist_node

    plan = [Subtask(id="1", description="write output file", assigned_agent="code")]
    state = _base_state(
        execution_plan=plan,
        current_subtask_index=0,
        agent_outputs={},
        retries={},
        escalation_required=False,
    )
    result = await partial(specialist_node, agent_type="code")(state)
    assert result["escalation_required"] is True
    assert result["escalation_trigger"] == "sensitive_operation"
    assert result["status"] == "escalated"


@pytest.mark.asyncio
async def test_reviewer_escalates_low_score(monkeypatch):
    monkeypatch.setattr("app.agents.publisher.publish_status", lambda *a, **k: None)
    monkeypatch.setattr("app.memory.memory_manager.MemoryManager.get_memory_context", _FakeMemoryManager.get_memory_context)

    from app.agents.reviewer import reviewer_node

    async def mock_review(self, state):
        return {
            "status": "escalated",
            "escalation_required": True,
            "escalation_trigger": "low_reviewer_score",
            "escalation_reason": "score too low",
            "reviewer_score": 0.3,
        }

    monkeypatch.setattr("app.agents.reviewer.ReviewerAgent.review", mock_review)

    state = _base_state()
    result = await reviewer_node(state)
    assert result["escalation_required"] is True
    assert result["escalation_trigger"] == "low_reviewer_score"
    assert result["status"] == "escalated"


@pytest.mark.asyncio
async def test_user_requested_escalation_endpoint(client: AsyncClient, monkeypatch):
    published = []

    class _FakeRedis:
        async def publish(self, channel, message):
            published.append((channel, json.loads(message)))

        async def close(self):
            pass

    monkeypatch.setattr(
        "app.api.v1.tasks.redis.from_url", lambda *a, **k: _FakeRedis()
    )

    response = await client.post("/api/v1/tasks/task-1/escalate")
    assert response.status_code == 200
    data = response.json()
    assert data.get("task_id") == "task-1"
    assert data.get("status") == "escalation_requested"
    assert any(
        channel == "task_control:task-1" and payload.get("trigger") == "user_requested"
        for channel, payload in published
    )


@pytest.mark.asyncio
async def test_chat_stores_and_returns_messages_in_order(client: AsyncClient, monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self._lists = {}

        async def lrange(self, key, start, end):
            return self._lists.get(key, [])

        async def rpush(self, key, value):
            self._lists.setdefault(key, []).append(value)

        async def expire(self, key, ttl):
            pass

        async def close(self):
            pass

    fake_redis = _FakeRedis()

    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(
        "app.api.v1.approval_requests._get_redis", _fake_get_redis
    )

    await client.post(
        "/api/v1/reviews/req-1/chat",
        json={"role": "user", "content": "first"},
    )
    await client.post(
        "/api/v1/reviews/req-1/chat",
        json={"role": "agent", "content": "second"},
    )
    response = await client.get("/api/v1/reviews/req-1/chat")
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) == 2
    assert messages[0]["content"] == "first"
    assert messages[1]["content"] == "second"
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "agent"


@pytest.mark.asyncio
async def test_graph_escalate_node_approve_with_modified_plan(monkeypatch):
    monkeypatch.setattr("app.agents.publisher.publish_status", lambda *a, **k: None)

    modified_plan = [
        {"id": "new-1", "description": "New plan item", "assigned_agent": "research"}
    ]
    fake_request = _FakeApprovalRequest(modified_plan=modified_plan)

    async def mock_escalate(*args, **kwargs):
        return fake_request

    async def mock_wait_for_resolution(*args, **kwargs):
        return {"decision": "approve"}

    async def mock_get_by_id(*args, **kwargs):
        return fake_request

    monkeypatch.setattr(
        "app.agents.graph._wait_for_resolution", mock_wait_for_resolution
    )

    escalation_service = MagicMock()
    escalation_service.escalate = mock_escalate
    escalation_service.get_by_id = mock_get_by_id

    state = _base_state(
        escalation_required=True,
        escalation_trigger="low_confidence",
        escalation_service=escalation_service,
    )
    result = await _escalate_node(state)
    assert result["status"] == "executing"
    assert result["escalation_required"] is False
    assert len(result["execution_plan"]) == 1
    assert result["execution_plan"][0].id == "new-1"
    assert result["current_subtask_index"] == 0


@pytest.mark.asyncio
async def test_escalate_publishes_approval_required_within_one_second(monkeypatch):
    published = []

    class _FakeRedis:
        async def publish(self, channel, message):
            published.append((channel, message))

    async def fake_create(*args, **kwargs):
        return _FakeApprovalRequest()

    monkeypatch.setattr(
        "app.services.escalation_service.create_approval_request_from_state", fake_create
    )

    from app.services.escalation_service import EscalationService

    service = EscalationService(
        memory_manager=_FakeMemoryManager(), redis_client=_FakeRedis()
    )
    state = _base_state()

    start = datetime.now(timezone.utc)
    await service.escalate(
        state=state,
        trigger="low_confidence",
        proposed_action="wait",
        agent_reasoning="test",
    )
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    assert elapsed < 1.0
    approval_messages = [
        (channel, msg)
        for channel, msg in published
        if channel == f"approvals:{state['user_id']}"
        and json.loads(msg).get("event") == "approval_required"
    ]
    assert len(approval_messages) == 1
