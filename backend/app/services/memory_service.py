"""Memory business logic."""
from app.schemas.memory import MemoryQuery, MemoryResult


async def query_memory(query: MemoryQuery) -> list[MemoryResult]:
    raise NotImplementedError
