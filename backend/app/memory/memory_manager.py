"""Unified memory interface for agents."""
from dataclasses import dataclass
from typing import Any

from app.memory.long_term_memory import LongTermMemory, LongTermMemoryError, MemoryEntry
from app.memory.postgres_memory_store import PostgresMemoryStore, PostgresMemoryStoreError
from app.memory.working_memory import WorkingMemory, WorkingMemoryError


@dataclass
class MemoryContext:
    """Aggregated memory context returned to the supervisor."""

    similar_tasks: list[MemoryEntry]
    facts: list[str]
    working_outputs: dict[str, str]


class MemoryManager:
    """Single interface combining Redis working memory, ChromaDB semantic memory, and Postgres structured memory."""

    def __init__(
        self,
        working_memory: WorkingMemory | None = None,
        long_term_memory: LongTermMemory | None = None,
        postgres_store: PostgresMemoryStore | None = None,
    ) -> None:
        self.working = working_memory or WorkingMemory()
        self.long_term = long_term_memory or LongTermMemory()
        self.postgres = postgres_store or PostgresMemoryStore()

    async def initialize_task(
        self,
        task_id: str,
        user_id: str,
        description: str,
        plan: list[Any],
    ) -> None:
        """Persist the plan to Redis and log the task to Postgres."""
        plan_dicts = [self._subtask_to_dict(p) for p in plan]

        await self.working.save_plan(task_id, plan_dicts)
        await self.working.save_intermediate(task_id, "description", description)
        await self.working.save_intermediate(task_id, "user_id", user_id)

        await self.postgres.log_task(
            task_id=task_id,
            user_id=user_id,
            description=description,
            status="planning",
            plan_json=plan_dicts,
            final_output=None,
            confidence_score=None,
            reviewer_score=None,
            duration_ms=None,
            cost_usd=None,
        )

    async def save_specialist_output(
        self,
        task_id: str,
        subtask_id: str,
        output: str,
        tools_used: list[str],
    ) -> None:
        """Persist a specialist subtask output to Redis working memory."""
        await self.working.save_output(task_id, subtask_id, output)
        await self.working.save_intermediate(
            task_id, f"tools:{subtask_id}", tools_used
        )

    async def finalize_task(
        self,
        task_id: str,
        user_id: str,
        final_output: str,
        reviewer_score: float,
        confidence_score: float,
        duration_ms: float,
        cost_usd: float,
        tags: list[str],
    ) -> None:
        """Update Postgres, store the result in ChromaDB, and clear Redis working memory."""
        working_outputs = await self.working.get_all_outputs(task_id)
        tools = set()
        for subtask_id in working_outputs:
            try:
                subtask_tools = await self.working.get_intermediate(
                    task_id, f"tools:{subtask_id}"
                )
                if isinstance(subtask_tools, list):
                    tools.update(subtask_tools)
            except WorkingMemoryError:
                pass

        description = (
            await self.working.get_intermediate(task_id, "description") or ""
        )

        await self.postgres.update_task_status(
            task_id=task_id,
            status="complete",
            final_output=final_output,
        )

        await self.long_term.store_task_result(
            task_id=task_id,
            user_id=user_id,
            task_description=description,
            final_output=final_output,
            tools_used=list(tools),
            reviewer_score=reviewer_score,
            tags=tags,
        )

        await self.working.clear_task(task_id)

    async def get_memory_context(
        self, task_id: str, user_id: str, query: str
    ) -> MemoryContext:
        """Retrieve similar tasks, facts, and current working outputs for a task."""
        similar_tasks = await self.long_term.retrieve_similar(query, user_id)
        facts = await self.long_term.retrieve_facts(query, user_id)
        working_outputs = await self.working.get_all_outputs(task_id)
        return MemoryContext(
            similar_tasks=similar_tasks,
            facts=facts,
            working_outputs=working_outputs,
        )

    async def save_fact(self, user_id: str, fact: str, source: str) -> str:
        """Store a user fact in ChromaDB."""
        return await self.long_term.store_fact(
            user_id=user_id, fact=fact, source=source, importance=0.5
        )

    async def delete_memory(self, memory_id: str, user_id: str) -> bool:
        """Delete a memory entry from ChromaDB and Postgres."""
        deleted_chroma = False
        deleted_postgres = False

        try:
            await self.long_term.delete_entry(memory_id)
            deleted_chroma = True
        except LongTermMemoryError:
            pass

        try:
            await self.postgres.delete_memory_entry(memory_id)
            deleted_postgres = True
        except PostgresMemoryStoreError:
            pass

        return deleted_chroma or deleted_postgres

    async def list_memories(self, user_id: str) -> list[MemoryEntry]:
        """List semantic memory entries for a user."""
        return await self.long_term.list_entries(user_id)

    async def close(self) -> None:
        """Close underlying store connections."""
        await self.working.close()
        await self.long_term.close()

    @staticmethod
    def _subtask_to_dict(subtask: Any) -> dict:
        if isinstance(subtask, dict):
            return subtask
        if hasattr(subtask, "model_dump"):
            return subtask.model_dump()
        if hasattr(subtask, "dict"):
            return subtask.dict()
        return {"data": str(subtask)}
