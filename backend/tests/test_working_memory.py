"""WorkingMemory Redis layer tests."""
import pytest

from app.memory.working_memory import WorkingMemory, WorkingMemoryError


class _FakeAsyncRedis:
    """In-memory async Redis stand-in for unit tests."""

    def __init__(self):
        self._data: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._data[key] = value

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def scan_iter(self, match: str):
        pattern = match.replace("*", "")
        for key in list(self._data.keys()):
            if key.startswith(pattern):
                yield key

    async def delete(self, *keys) -> int:
        for key in keys:
            self._data.pop(key, None)
        return len(keys)

    async def close(self) -> None:
        pass


@pytest.fixture
def working_memory(monkeypatch):
    wm = WorkingMemory()
    fake = _FakeAsyncRedis()
    monkeypatch.setattr(wm, "_client", fake)
    return wm


@pytest.mark.asyncio
async def test_save_and_get_plan(working_memory):
    plan = [{"id": "1", "agent": "research", "description": "search"}]
    await working_memory.save_plan("task-1", plan)
    assert await working_memory.get_plan("task-1") == plan


@pytest.mark.asyncio
async def test_save_and_get_outputs(working_memory):
    await working_memory.save_output("task-1", "1", "output one")
    await working_memory.save_output("task-1", "2", "output two")
    assert await working_memory.get_all_outputs("task-1") == {
        "1": "output one",
        "2": "output two",
    }


@pytest.mark.asyncio
async def test_intermediate_storage(working_memory):
    await working_memory.save_intermediate("task-1", "counter", 42)
    await working_memory.save_intermediate("task-1", "flag", True)
    assert await working_memory.get_intermediate("task-1", "counter") == 42
    assert await working_memory.get_intermediate("task-1", "flag") is True
    assert await working_memory.get_intermediate("task-1", "missing") is None


@pytest.mark.asyncio
async def test_error_storage(working_memory):
    await working_memory.save_error("task-1", "2", "something went wrong")
    errors = await working_memory.get_errors("task-1")
    assert len(errors) == 1
    assert errors[0]["subtask_id"] == "2"
    assert errors[0]["error"] == "something went wrong"


@pytest.mark.asyncio
async def test_clear_task(working_memory):
    await working_memory.save_plan("task-1", [{"id": "1"}])
    await working_memory.save_output("task-1", "1", "out")
    await working_memory.save_intermediate("task-1", "key", "value")
    await working_memory.save_error("task-1", "1", "err")

    await working_memory.clear_task("task-1")

    assert await working_memory.get_plan("task-1") == []
    assert await working_memory.get_all_outputs("task-1") == {}
    assert await working_memory.get_intermediate("task-1", "key") is None
    assert await working_memory.get_errors("task-1") == []


@pytest.mark.asyncio
async def test_key_namespacing_isolation(working_memory):
    await working_memory.save_output("task-1", "1", "a")
    await working_memory.save_output("task-2", "1", "b")
    assert await working_memory.get_all_outputs("task-1") == {"1": "a"}
    assert await working_memory.get_all_outputs("task-2") == {"1": "b"}


@pytest.mark.asyncio
async def test_connection_failure_raises_working_memory_error(monkeypatch):
    def broken_from_url(url, **kwargs):
        raise ConnectionError("refused")

    monkeypatch.setattr("redis.asyncio.from_url", broken_from_url)
    wm = WorkingMemory()
    with pytest.raises(WorkingMemoryError) as exc_info:
        await wm.get_plan("task-1")
    assert "Failed to connect to Redis working memory" in str(exc_info.value)
