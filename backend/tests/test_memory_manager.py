"""MemoryManager unification tests."""
import json
import uuid

import pytest

from app.memory.memory_manager import MemoryContext, MemoryManager
from app.memory.long_term_memory import MemoryEntry


class _FakeWorkingMemory:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def save_plan(self, task_id: str, plan: list[dict]) -> None:
        self.data[f"task:{task_id}:plan:0"] = json.dumps(plan)

    async def get_plan(self, task_id: str) -> list[dict]:
        value = self.data.get(f"task:{task_id}:plan:0")
        return json.loads(value) if value else []

    async def save_output(self, task_id: str, subtask_id: str, output: str) -> None:
        self.data[f"task:{task_id}:output:{subtask_id}"] = output

    async def get_all_outputs(self, task_id: str) -> dict[str, str]:
        prefix = f"task:{task_id}:output:"
        return {k.split(":")[-1]: v for k, v in self.data.items() if k.startswith(prefix)}

    async def save_intermediate(self, task_id: str, key: str, value) -> None:
        self.data[f"task:{task_id}:intermediate:{key}"] = json.dumps(value)

    async def get_intermediate(self, task_id: str, key: str):
        value = self.data.get(f"task:{task_id}:intermediate:{key}")
        return json.loads(value) if value else None

    async def save_error(self, task_id: str, subtask_id: str, error: str) -> None:
        self.data[f"task:{task_id}:error:{subtask_id}"] = error

    async def get_errors(self, task_id: str) -> list[dict]:
        return []

    async def clear_task(self, task_id: str) -> None:
        prefix = f"task:{task_id}:"
        self.data = {k: v for k, v in self.data.items() if not k.startswith(prefix)}

    async def close(self) -> None:
        pass


class _FakeLongTermMemory:
    def __init__(self):
        self.task_results: list[dict] = []
        self.facts: list[dict] = []
        self.deleted: list[str] = []

    async def store_task_result(self, **kwargs) -> str:
        self.task_results.append(kwargs)
        return "task-mem-1"

    async def retrieve_similar(self, query: str, user_id: str, n: int = 5) -> list[MemoryEntry]:
        return [
            MemoryEntry(
                id="mem-1",
                task_description="Past task",
                summary="Past summary",
                tools_used=["web_search"],
                reviewer_score=0.8,
                created_at="2024-01-01T00:00:00",
                tags=["ai"],
                importance_score=0.7,
            )
        ]

    async def store_fact(self, user_id: str, fact: str, source: str, importance: float) -> str:
        self.facts.append({"fact": fact, "source": source, "importance": importance})
        return "fact-1"

    async def retrieve_facts(self, query: str, user_id: str, n: int = 3) -> list[str]:
        return [f["fact"] for f in self.facts]

    async def delete_entry(self, memory_id: str) -> None:
        self.deleted.append(memory_id)

    async def list_entries(self, user_id: str) -> list[MemoryEntry]:
        return []

    async def close(self) -> None:
        pass


class _FakePostgresStore:
    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self.invocations: list[dict] = []
        self.memories: dict[str, dict] = {}

    async def log_task(self, **kwargs) -> uuid.UUID:
        self.tasks[kwargs["task_id"]] = kwargs
        return uuid.uuid4()

    async def update_task_status(
        self, task_id: str, status: str, final_output: str | None = None, error: str | None = None
    ) -> None:
        self.tasks.setdefault(task_id, {})
        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["final_output"] = final_output

    async def log_tool_invocation(self, **kwargs) -> uuid.UUID:
        self.invocations.append(kwargs)
        return uuid.uuid4()

    async def get_task_history(self, user_id: str, limit: int = 20) -> list:
        return []

    async def get_tool_stats(self, user_id: str) -> dict:
        return {}

    async def save_memory_entry(self, **kwargs) -> uuid.UUID:
        self.memories[kwargs["memory_id"]] = kwargs
        return uuid.uuid4()

    async def delete_memory_entry(self, memory_id: str) -> None:
        self.memories.pop(memory_id, None)

    async def list_memory_entries(self, user_id: str) -> list:
        return []


@pytest.fixture
def manager():
    return MemoryManager(
        working_memory=_FakeWorkingMemory(),
        long_term_memory=_FakeLongTermMemory(),
        postgres_store=_FakePostgresStore(),
    )


@pytest.mark.asyncio
async def test_initialize_task_persists_plan_and_logs_task(manager):
    task_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    plan = [{"id": "1", "agent": "research", "description": "search"}]
    await manager.initialize_task(task_id, user_id, "Test task", plan)

    assert await manager.working.get_plan(task_id) == plan
    assert manager.postgres.tasks[task_id]["description"] == "Test task"
    assert manager.postgres.tasks[task_id]["status"] == "planning"


@pytest.mark.asyncio
async def test_save_specialist_output(manager):
    task_id = str(uuid.uuid4())
    await manager.save_specialist_output(task_id, "1", "output one", ["web_search"])
    assert await manager.working.get_all_outputs(task_id) == {"1": "output one"}
    assert await manager.working.get_intermediate(task_id, "tools:1") == ["web_search"]


@pytest.mark.asyncio
async def test_finalize_task_updates_all_stores(manager):
    task_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    await manager.initialize_task(task_id, user_id, "Test task", [])
    await manager.save_specialist_output(task_id, "1", "output one", ["web_search"])

    await manager.finalize_task(
        task_id=task_id,
        user_id=user_id,
        final_output="Final result",
        reviewer_score=0.85,
        confidence_score=0.9,
        duration_ms=1200.0,
        cost_usd=0.02,
        tags=["ai"],
    )

    assert manager.postgres.tasks[task_id]["status"] == "complete"
    assert manager.postgres.tasks[task_id]["final_output"] == "Final result"
    assert len(manager.long_term.task_results) == 1
    assert manager.long_term.task_results[0]["final_output"] == "Final result"
    assert manager.working.data == {}


@pytest.mark.asyncio
async def test_get_memory_context(manager):
    task_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    await manager.save_fact(user_id, "Prefers Python", "onboarding")
    await manager.save_specialist_output(task_id, "1", "working output", ["tool"])

    context = await manager.get_memory_context(task_id, user_id, "python")
    assert isinstance(context, MemoryContext)
    assert len(context.similar_tasks) == 1
    assert context.facts == ["Prefers Python"]
    assert context.working_outputs == {"1": "working output"}


@pytest.mark.asyncio
async def test_delete_memory(manager):
    user_id = str(uuid.uuid4())
    memory_id = str(uuid.uuid4())
    await manager.save_memory_entry(user_id, memory_id, "Fact", 0.9, ["tag"])
    assert memory_id in manager.postgres.memories

    deleted = await manager.delete_memory(memory_id, user_id)
    assert deleted is True
    assert memory_id not in manager.postgres.memories
    assert memory_id in manager.long_term.deleted


@pytest.mark.asyncio
async def test_close(manager):
    await manager.close()
    # Fakes have no-op close; just ensure no exception is raised.
