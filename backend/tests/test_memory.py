"""Cross-cutting memory layer tests: Redis TTL, ChromaDB similarity, and MemoryManager integration."""
import json

import pytest

from app.memory.long_term_memory import LongTermMemory, MemoryEntry
from app.memory.memory_manager import MemoryContext, MemoryManager
from app.memory.working_memory import WorkingMemory


# ---------------------------------------------------------------------------
# Redis TTL test
# ---------------------------------------------------------------------------
class _FakeRedisWithTTL:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def scan_iter(self, match: str):
        prefix = match.replace("*", "")
        for key in list(self.data.keys()):
            if key.startswith(prefix):
                yield key

    async def delete(self, *keys) -> int:
        for key in keys:
            self.data.pop(key, None)
            self.ttls.pop(key, None)
        return len(keys)

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_working_memory_applies_24_hour_ttl():
    wm = WorkingMemory()
    wm._client = _FakeRedisWithTTL()

    await wm.save_output("task-1", "1", "output one")
    await wm.save_intermediate("task-1", "counter", 42)

    assert wm._client.ttls["task:task-1:output:1"] == 24 * 60 * 60
    assert wm._client.ttls["task:task-1:intermediate:counter"] == 24 * 60 * 60


# ---------------------------------------------------------------------------
# ChromaDB similarity retrieval test
# ---------------------------------------------------------------------------
class _FakeEmbeddingFunction:
    def __call__(self, input: list[str]) -> list[list[float]]:
        return [[float(len(text))] * 384 for _ in input]


class _FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.docs: dict[str, dict] = {}

    def add(self, ids: list[str], documents: list[str], metadatas: list[dict]):
        for i, memory_id in enumerate(ids):
            self.docs[memory_id] = {
                "document": documents[i],
                "metadata": metadatas[i],
            }

    def query(self, query_texts: list[str], n_results: int, where: dict | None = None):
        filtered = {
            memory_id: doc
            for memory_id, doc in self.docs.items()
            if self._matches(doc["metadata"], where)
        }
        selected = list(filtered.items())[:n_results]
        return {
            "ids": [[memory_id for memory_id, _ in selected]],
            "documents": [[doc["document"] for _, doc in selected]],
            "metadatas": [[doc["metadata"] for _, doc in selected]],
        }

    def get(self, where: dict | None = None, limit: int | None = None, include=None):
        filtered = {
            memory_id: doc
            for memory_id, doc in self.docs.items()
            if self._matches(doc["metadata"], where)
        }
        if limit is not None:
            filtered = dict(list(filtered.items())[:limit])
        return {
            "ids": list(filtered.keys()),
            "metadatas": [doc["metadata"] for doc in filtered.values()],
        }

    def delete(self, ids: list[str]):
        for memory_id in ids:
            self.docs.pop(memory_id, None)

    @staticmethod
    def _matches(metadata: dict, where: dict | None) -> bool:
        if not where:
            return True
        return all(metadata.get(k) == v for k, v in where.items())


class _FakeChromaClient:
    def __init__(self):
        self.collections: dict[str, _FakeCollection] = {}

    def get_or_create_collection(self, name: str, embedding_function=None):
        if name not in self.collections:
            self.collections[name] = _FakeCollection(name)
        return self.collections[name]


@pytest.mark.asyncio
async def test_long_term_memory_retrieves_similar_tasks_for_user():
    ltm = LongTermMemory()
    ltm._client = _FakeChromaClient()
    ltm._embedding_function = _FakeEmbeddingFunction()

    await ltm.store_task_result(
        task_id="task-1",
        user_id="user-1",
        task_description="Research AI orchestration",
        final_output="AI orchestration summary",
        tools_used=["web_search"],
        reviewer_score=0.85,
        tags=["ai"],
    )
    await ltm.store_task_result(
        task_id="task-2",
        user_id="user-2",
        task_description="Bake a cake",
        final_output="Cake recipe",
        tools_used=["read_file"],
        reviewer_score=0.9,
        tags=["cooking"],
    )

    entries = await ltm.retrieve_similar("AI orchestration", user_id="user-1", n=5)
    assert len(entries) == 1
    assert entries[0].task_description == "Research AI orchestration"


# ---------------------------------------------------------------------------
# MemoryManager.get_memory_context integration test
# ---------------------------------------------------------------------------
class _FakeWorkingMemory:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def save_output(self, task_id: str, subtask_id: str, output: str) -> None:
        self.data[f"task:{task_id}:output:{subtask_id}"] = output

    async def get_all_outputs(self, task_id: str) -> dict[str, str]:
        prefix = f"task:{task_id}:output:"
        return {k.split(":")[-1]: v for k, v in self.data.items() if k.startswith(prefix)}

    async def close(self) -> None:
        pass


class _FakeLongTermMemory:
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

    async def retrieve_facts(self, query: str, user_id: str, n: int = 3) -> list[str]:
        return ["User prefers Python"]

    async def close(self) -> None:
        pass


class _FakePostgresStore:
    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_memory_manager_get_memory_context_aggregates_all_backends():
    working = _FakeWorkingMemory()
    await working.save_output("task-1", "1", "working output one")

    manager = MemoryManager(
        working_memory=working,
        long_term_memory=_FakeLongTermMemory(),
        postgres_store=_FakePostgresStore(),
    )

    context = await manager.get_memory_context("task-1", "user-1", "python")

    assert isinstance(context, MemoryContext)
    assert len(context.similar_tasks) == 1
    assert context.similar_tasks[0].task_description == "Past task"
    assert context.facts == ["User prefers Python"]
    assert context.working_outputs == {"1": "working output one"}
