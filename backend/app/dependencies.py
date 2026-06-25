"""FastAPI dependency providers."""
from fastapi import Request

from app.memory.memory_manager import MemoryManager
from app.memory.working_memory import WorkingMemory
from app.memory.long_term_memory import LongTermMemory
from app.memory.postgres_memory_store import PostgresMemoryStore
from app.services.escalation_service import EscalationService


def get_memory_manager(request: Request) -> MemoryManager:
    """Return the app-level singleton MemoryManager, falling back to a fresh instance."""
    mm = getattr(request.app.state, "memory_manager", None)
    if mm is not None:
        return mm
    return MemoryManager(
        working_memory=WorkingMemory(),
        long_term_memory=LongTermMemory(),
        postgres_store=PostgresMemoryStore(),
    )


def get_escalation_service(request: Request) -> EscalationService:
    """Return an EscalationService wired to the singleton MemoryManager."""
    return EscalationService(memory_manager=get_memory_manager(request))
