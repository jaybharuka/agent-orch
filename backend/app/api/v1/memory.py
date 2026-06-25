"""Memory endpoints."""
from fastapi import APIRouter, Depends

from app.dependencies import get_memory_manager
from app.memory.memory_manager import MemoryManager
from app.schemas.memory import MemoryQuery, MemoryResult

router = APIRouter()


@router.post("/query", response_model=list[MemoryResult])
async def query_memory(
    payload: MemoryQuery,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    try:
        entries = await memory_manager.long_term.retrieve_similar(
            payload.query,
            user_id=str(payload.session_id) if payload.session_id else "",
            n=payload.top_k,
        )
        return [
            MemoryResult(
                id=e.id,
                content=f"{e.task_description}: {e.summary}",
                score=e.importance_score,
                metadata={
                    "tools_used": e.tools_used,
                    "reviewer_score": e.reviewer_score,
                    "tags": e.tags,
                    "created_at": e.created_at,
                },
            )
            for e in entries
        ]
    except Exception:
        return []
