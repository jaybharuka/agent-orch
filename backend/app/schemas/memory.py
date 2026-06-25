"""Memory schemas."""
from pydantic import BaseModel
from uuid import UUID


class MemoryQuery(BaseModel):
    query: str
    session_id: UUID | None = None
    top_k: int = 5


class MemoryResult(BaseModel):
    id: str
    content: str
    score: float
    metadata: dict
