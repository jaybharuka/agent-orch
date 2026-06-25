"""Structured Postgres memory store for tasks, tool invocations, and memory entries."""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.db.session import async_session
from app.models.memory import MemoryEntry as MemoryEntryModel
from app.models.task import Task
from app.models.tool_invocation import ToolInvocation


class PostgresMemoryStoreError(Exception):
    """Raised when Postgres memory operations fail."""


@dataclass
class TaskRecord:
    """A task record returned by the memory store."""

    id: str
    user_id: str
    description: str
    status: str
    plan_json: Any
    final_output: str | None
    confidence_score: float | None
    reviewer_score: float | None
    duration_ms: float | None
    cost_usd: float | None
    created_at: datetime
    updated_at: datetime | None


@dataclass
class MemoryRecord:
    """A memory entry record returned by the memory store."""

    id: str
    user_id: str
    description: str
    importance_score: float | None
    tags: list[str]
    created_at: datetime


class PostgresMemoryStore:
    """Async SQLAlchemy store for structured agent memory in PostgreSQL."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def _to_uuid(value: str | uuid.UUID) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError):
            return uuid.uuid4()

    async def log_task(
        self,
        task_id: str,
        user_id: str,
        description: str,
        status: str,
        plan_json: Any,
        final_output: str | None,
        confidence_score: float | None,
        reviewer_score: float | None,
        duration_ms: float | None,
        cost_usd: float | None,
    ) -> uuid.UUID:
        """Create a task record in Postgres."""
        task_uuid = self._to_uuid(task_id)
        user_uuid = self._to_uuid(user_id)

        async with async_session() as session:
            try:
                task = Task(
                    id=task_uuid,
                    session_id=user_uuid,
                    user_id=user_uuid,
                    description=description,
                    status=status,
                    plan_json=plan_json,
                    final_output=final_output,
                    confidence_score=confidence_score,
                    reviewer_score=reviewer_score,
                    duration_ms=duration_ms,
                    cost_usd=cost_usd,
                )
                session.add(task)
                await session.commit()
                return task_uuid
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to log task {task_id}: {exc}"
                ) from exc

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        final_output: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update a task's status and optional final output / error."""
        task_uuid = self._to_uuid(task_id)

        async with async_session() as session:
            try:
                task = await session.get(Task, task_uuid)
                if task is None:
                    raise PostgresMemoryStoreError(
                        f"Task {task_id} not found for status update"
                    )
                task.status = status
                if final_output is not None:
                    task.final_output = final_output
                if error is not None:
                    task.result = {"error": error}
                await session.commit()
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to update task status for {task_id}: {exc}"
                ) from exc

    async def log_tool_invocation(
        self,
        task_id: str,
        subtask_id: str,
        tool_name: str,
        inputs_json: Any,
        output_json: Any,
        latency_ms: float,
        error: str | None = None,
    ) -> uuid.UUID:
        """Create a tool invocation record linked to a task and subtask."""
        task_uuid = self._to_uuid(task_id)

        async with async_session() as session:
            try:
                invocation = ToolInvocation(
                    task_id=task_uuid,
                    subtask_id=subtask_id,
                    tool_name=tool_name,
                    inputs=inputs_json,
                    output=output_json,
                    latency_ms=latency_ms,
                    error=error,
                )
                session.add(invocation)
                await session.commit()
                return invocation.id
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to log tool invocation for task {task_id}: {exc}"
                ) from exc

    async def get_task_history(
        self, user_id: str, limit: int = 20
    ) -> list[TaskRecord]:
        """Return the most recent tasks for a user."""
        user_uuid = self._to_uuid(user_id)

        async with async_session() as session:
            try:
                result = await session.execute(
                    select(Task)
                    .where(Task.user_id == user_uuid)
                    .order_by(Task.created_at.desc())
                    .limit(limit)
                )
                tasks = result.scalars().all()
                return [
                    TaskRecord(
                        id=str(t.id),
                        user_id=str(t.user_id),
                        description=t.description or "",
                        status=t.status or "",
                        plan_json=t.plan_json,
                        final_output=t.final_output,
                        confidence_score=t.confidence_score,
                        reviewer_score=t.reviewer_score,
                        duration_ms=t.duration_ms,
                        cost_usd=t.cost_usd,
                        created_at=t.created_at,
                        updated_at=t.updated_at,
                    )
                    for t in tasks
                ]
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to get task history for user {user_id}: {exc}"
                ) from exc

    async def get_tool_stats(self, user_id: str) -> dict[str, dict]:
        """Return aggregated tool usage statistics for a user."""
        user_uuid = self._to_uuid(user_id)

        async with async_session() as session:
            try:
                result = await session.execute(
                    select(
                        ToolInvocation.tool_name,
                        func.avg(ToolInvocation.latency_ms).label("avg_latency"),
                        func.count(ToolInvocation.id).label("count"),
                        func.sum(
                            func.case(
                                (ToolInvocation.error.is_(None), 1),
                                else_=0,
                            )
                        ).label("success_count"),
                    )
                    .join(Task, ToolInvocation.task_id == Task.id)
                    .where(Task.user_id == user_uuid)
                    .group_by(ToolInvocation.tool_name)
                )
                stats: dict[str, dict] = {}
                for row in result:
                    count = row.count
                    success_count = row.success_count or 0
                    success_rate = success_count / count if count > 0 else 0.0
                    stats[row.tool_name] = {
                        "avg_latency": round(float(row.avg_latency), 2)
                        if row.avg_latency
                        else 0.0,
                        "success_rate": round(success_rate, 2),
                        "count": count,
                    }
                return stats
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to get tool stats for user {user_id}: {exc}"
                ) from exc

    async def save_memory_entry(
        self,
        user_id: str,
        memory_id: str,
        description: str,
        importance_score: float,
        tags: list[str],
    ) -> uuid.UUID:
        """Create a memory entry in Postgres."""
        user_uuid = self._to_uuid(user_id)
        memory_uuid = self._to_uuid(memory_id)

        async with async_session() as session:
            try:
                entry = MemoryEntryModel(
                    id=memory_uuid,
                    session_id=user_uuid,
                    user_id=user_uuid,
                    memory_type="postgres",
                    content=description,
                    importance_score=importance_score,
                    tags=tags,
                    metadata_={"source": "postgres_memory_store"},
                )
                session.add(entry)
                await session.commit()
                return memory_uuid
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to save memory entry {memory_id}: {exc}"
                ) from exc

    async def delete_memory_entry(self, memory_id: str) -> None:
        """Hard delete a memory entry by id."""
        memory_uuid = self._to_uuid(memory_id)

        async with async_session() as session:
            try:
                entry = await session.get(MemoryEntryModel, memory_uuid)
                if entry is None:
                    raise PostgresMemoryStoreError(
                        f"Memory entry {memory_id} not found"
                    )
                await session.delete(entry)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to delete memory entry {memory_id}: {exc}"
                ) from exc

    async def list_memory_entries(self, user_id: str) -> list[MemoryRecord]:
        """Return memory entries for a user."""
        user_uuid = self._to_uuid(user_id)

        async with async_session() as session:
            try:
                result = await session.execute(
                    select(MemoryEntryModel)
                    .where(MemoryEntryModel.user_id == user_uuid)
                    .order_by(MemoryEntryModel.created_at.desc())
                )
                entries = result.scalars().all()
                return [
                    MemoryRecord(
                        id=str(e.id),
                        user_id=str(e.user_id),
                        description=e.content or "",
                        importance_score=e.importance_score,
                        tags=e.tags or [],
                        created_at=e.created_at,
                    )
                    for e in entries
                ]
            except Exception as exc:
                await session.rollback()
                raise PostgresMemoryStoreError(
                    f"Failed to list memory entries for user {user_id}: {exc}"
                ) from exc
