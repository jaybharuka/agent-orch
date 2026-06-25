"""PostgresMemoryStore unit tests using a fake async session."""
import uuid
from datetime import datetime

import pytest

from app.memory.postgres_memory_store import (
    MemoryRecord,
    PostgresMemoryStore,
    PostgresMemoryStoreError,
    TaskRecord,
)
from app.models.memory import MemoryEntry as MemoryEntryModel
from app.models.task import Task
from app.models.tool_invocation import ToolInvocation


class _FakeResult:
    def __init__(self, scalars):
        self._scalars = scalars

    def scalars(self):
        return _FakeScalar(self._scalars)


class _FakeScalar:
    def __init__(self, data):
        self._data = data

    def all(self):
        return self._data


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, get_returns=None, execute_returns=None):
        self.added: list = []
        self.deleted: list = []
        self.committed = False
        self.rolled_back = False
        self._get_returns = get_returns or {}
        self._execute_returns = execute_returns or []

    def __call__(self):
        return _FakeSessionContext(self)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def get(self, model, obj_id):
        return self._get_returns.get((model, obj_id))

    async def execute(self, query):
        return _FakeResult(self._execute_returns)

    async def delete(self, obj):
        self.deleted.append(obj)


@pytest.fixture
def store(monkeypatch):
    fake_session = _FakeSession()
    monkeypatch.setattr(
        "app.memory.postgres_memory_store.async_session", fake_session
    )
    return PostgresMemoryStore(), fake_session


@pytest.mark.asyncio
async def test_log_task_creates_task_object(store):
    s, session = store
    task_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    await s.log_task(
        task_id=task_id,
        user_id=user_id,
        description="Test task",
        status="complete",
        plan_json=[{"id": "1"}],
        final_output="Final",
        confidence_score=0.9,
        reviewer_score=0.85,
        duration_ms=1000,
        cost_usd=0.01,
    )
    assert len(session.added) == 1
    task = session.added[0]
    assert isinstance(task, Task)
    assert str(task.id) == task_id
    assert str(task.user_id) == user_id
    assert task.description == "Test task"
    assert task.status == "complete"
    assert task.plan_json == [{"id": "1"}]
    assert task.final_output == "Final"
    assert task.confidence_score == 0.9
    assert task.reviewer_score == 0.85
    assert task.duration_ms == 1000
    assert task.cost_usd == 0.01
    assert session.committed


@pytest.mark.asyncio
async def test_update_task_status(store):
    s, session = store
    task_id = uuid.uuid4()
    task = Task(id=task_id, session_id=uuid.uuid4(), user_id=uuid.uuid4(), status="pending")
    session._get_returns[(Task, task_id)] = task

    await s.update_task_status(str(task_id), "complete", final_output="Done", error="None")

    assert task.status == "complete"
    assert task.final_output == "Done"
    assert task.result == {"error": "None"}
    assert session.committed


@pytest.mark.asyncio
async def test_update_task_status_not_found(store):
    s, session = store
    with pytest.raises(PostgresMemoryStoreError):
        await s.update_task_status("missing-task-id", "complete")


@pytest.mark.asyncio
async def test_log_tool_invocation(store):
    s, session = store
    task_id = str(uuid.uuid4())
    invocation_id = await s.log_tool_invocation(
        task_id=task_id,
        subtask_id="sub-1",
        tool_name="web_search",
        inputs_json={"query": "ai"},
        output_json={"results": []},
        latency_ms=120.0,
        error=None,
    )
    assert invocation_id
    assert len(session.added) == 1
    invocation = session.added[0]
    assert isinstance(invocation, ToolInvocation)
    assert str(invocation.task_id) == task_id
    assert invocation.subtask_id == "sub-1"
    assert invocation.tool_name == "web_search"
    assert invocation.inputs == {"query": "ai"}
    assert invocation.output == {"results": []}
    assert invocation.latency_ms == 120.0
    assert invocation.error is None
    assert session.committed


@pytest.mark.asyncio
async def test_get_task_history(store):
    s, session = store
    user_id = str(uuid.uuid4())
    task = Task(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        description="History task",
        status="complete",
        plan_json={},
        final_output="Out",
        confidence_score=0.8,
        reviewer_score=0.75,
        duration_ms=500.0,
        cost_usd=0.005,
        created_at=datetime.utcnow(),
    )
    session._execute_returns = [task]

    records = await s.get_task_history(user_id)
    assert len(records) == 1
    assert isinstance(records[0], TaskRecord)
    assert records[0].description == "History task"


@pytest.mark.asyncio
async def test_get_tool_stats(store):
    s, session = store
    user_id = str(uuid.uuid4())
    Row = type("Row", (), {"tool_name": "web_search", "avg_latency": 150.0, "count": 10, "success_count": 9})
    session._execute_returns = [Row]

    stats = await s.get_tool_stats(user_id)
    assert stats["web_search"]["avg_latency"] == 150.0
    assert stats["web_search"]["count"] == 10
    assert stats["web_search"]["success_rate"] == 0.9


@pytest.mark.asyncio
async def test_save_memory_entry(store):
    s, session = store
    memory_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    await s.save_memory_entry(
        user_id=user_id,
        memory_id=memory_id,
        description="Important fact",
        importance_score=0.95,
        tags=["fact", "preference"],
    )
    assert len(session.added) == 1
    entry = session.added[0]
    assert isinstance(entry, MemoryEntryModel)
    assert str(entry.id) == memory_id
    assert str(entry.user_id) == user_id
    assert entry.content == "Important fact"
    assert entry.importance_score == 0.95
    assert entry.tags == ["fact", "preference"]
    assert session.committed


@pytest.mark.asyncio
async def test_delete_memory_entry(store):
    s, session = store
    memory_id = uuid.uuid4()
    entry = MemoryEntryModel(id=memory_id, content="To delete")
    session._get_returns[(MemoryEntryModel, memory_id)] = entry

    await s.delete_memory_entry(str(memory_id))

    assert session.deleted == [entry]
    assert session.committed


@pytest.mark.asyncio
async def test_delete_memory_entry_not_found(store):
    s, session = store
    with pytest.raises(PostgresMemoryStoreError):
        await s.delete_memory_entry("missing-mem-id")


@pytest.mark.asyncio
async def test_list_memory_entries(store):
    s, session = store
    user_id = str(uuid.uuid4())
    entry = MemoryEntryModel(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        content="Listed memory",
        importance_score=0.8,
        tags=["tag"],
        created_at=datetime.utcnow(),
    )
    session._execute_returns = [entry]

    records = await s.list_memory_entries(user_id)
    assert len(records) == 1
    assert isinstance(records[0], MemoryRecord)
    assert records[0].description == "Listed memory"
