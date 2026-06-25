"""LongTermMemory ChromaDB layer tests."""
import pytest

from app.memory.long_term_memory import (
    FACT_COLLECTION,
    LongTermMemory,
    LongTermMemoryError,
    TASK_COLLECTION,
)


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
        ids = [memory_id for memory_id, _ in selected]
        docs = [doc["document"] for _, doc in selected]
        metas = [doc["metadata"] for _, doc in selected]
        return {"ids": [ids], "documents": [docs], "metadatas": [metas]}

    def get(self, where: dict | None = None, limit: int | None = None, include=None):
        filtered = {
            memory_id: doc
            for memory_id, doc in self.docs.items()
            if self._matches(doc["metadata"], where)
        }
        if limit is not None:
            filtered = dict(list(filtered.items())[:limit])
        ids = list(filtered.keys())
        metadatas = [doc["metadata"] for doc in filtered.values()]
        return {"ids": ids, "metadatas": metadatas}

    def delete(self, ids: list[str]):
        for memory_id in ids:
            if memory_id not in self.docs:
                raise Exception(f"ID {memory_id} not found")
            del self.docs[memory_id]

    @staticmethod
    def _matches(metadata: dict, where: dict | None) -> bool:
        if not where:
            return True
        return all(metadata.get(k) == v for k, v in where.items())


class _FakeClient:
    def __init__(self):
        self.collections: dict[str, _FakeCollection] = {}

    def get_or_create_collection(self, name: str, embedding_function=None):
        if name not in self.collections:
            self.collections[name] = _FakeCollection(name)
        return self.collections[name]


@pytest.fixture
def ltm():
    memory = LongTermMemory()
    memory._client = _FakeClient()
    memory._embedding_function = _FakeEmbeddingFunction()
    return memory


@pytest.mark.asyncio
async def test_store_and_retrieve_task_result(ltm):
    memory_id = await ltm.store_task_result(
        task_id="task-1",
        user_id="user-1",
        task_description="Research AI orchestration",
        final_output="AI orchestration is...",
        tools_used=["web_search"],
        reviewer_score=0.85,
        tags=["ai", "orchestration"],
    )
    assert memory_id

    entries = await ltm.retrieve_similar("AI orchestration", user_id="user-1", n=5)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.task_description == "Research AI orchestration"
    assert entry.tools_used == ["web_search"]
    assert entry.tags == ["ai", "orchestration"]
    assert entry.reviewer_score == 0.85


@pytest.mark.asyncio
async def test_user_scoping(ltm):
    await ltm.store_task_result(
        task_id="task-1",
        user_id="user-1",
        task_description="User one task",
        final_output="out",
        tools_used=[],
        reviewer_score=0.8,
        tags=[],
    )
    await ltm.store_task_result(
        task_id="task-2",
        user_id="user-2",
        task_description="User two task",
        final_output="out",
        tools_used=[],
        reviewer_score=0.8,
        tags=[],
    )
    entries = await ltm.retrieve_similar("task", user_id="user-1")
    assert len(entries) == 1
    assert entries[0].task_description == "User one task"


@pytest.mark.asyncio
async def test_store_and_retrieve_facts(ltm):
    await ltm.store_fact(
        user_id="user-1",
        fact="Prefers Python for automation",
        source="onboarding",
        importance=0.9,
    )
    facts = await ltm.retrieve_facts("programming preference", user_id="user-1", n=3)
    assert len(facts) == 1
    assert "Python" in facts[0]


@pytest.mark.asyncio
async def test_delete_entry(ltm):
    memory_id = await ltm.store_task_result(
        task_id="task-1",
        user_id="user-1",
        task_description="Task to delete",
        final_output="out",
        tools_used=[],
        reviewer_score=0.8,
        tags=[],
    )
    await ltm.delete_entry(memory_id)
    entries = await ltm.retrieve_similar("delete", user_id="user-1")
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_delete_entry_not_found(ltm):
    with pytest.raises(LongTermMemoryError):
        await ltm.delete_entry("non-existent-id")


@pytest.mark.asyncio
async def test_list_entries(ltm):
    await ltm.store_task_result(
        task_id="task-1",
        user_id="user-1",
        task_description="List task",
        final_output="out",
        tools_used=["web_search"],
        reviewer_score=0.9,
        tags=["demo"],
    )
    entries = await ltm.list_entries(user_id="user-1")
    assert len(entries) == 1
    assert entries[0].task_description == "List task"
    assert entries[0].tools_used == ["web_search"]


@pytest.mark.asyncio
async def test_connection_failure_raises_long_term_memory_error(monkeypatch):
    def broken_http_client(host, **kwargs):
        raise ConnectionError("refused")

    monkeypatch.setattr("chromadb.HttpClient", broken_http_client)
    memory = LongTermMemory()
    with pytest.raises(LongTermMemoryError) as exc_info:
        await memory.list_entries(user_id="user-1")
    assert "Failed to connect to ChromaDB" in str(exc_info.value)
