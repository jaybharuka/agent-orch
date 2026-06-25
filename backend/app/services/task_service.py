"""Task business logic."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskRead


async def create_task(db: AsyncSession, payload: TaskCreate) -> TaskRead:
    task = Task(session_id=payload.session_id, payload=payload.payload)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return TaskRead.model_validate(task)


async def get_task(db: AsyncSession, task_id: str) -> TaskRead:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead.model_validate(task)


async def list_tasks(db: AsyncSession, session_id: str | None = None) -> list[TaskRead]:
    query = select(Task).order_by(Task.created_at.desc())
    if session_id is not None:
        query = query.where(Task.session_id == session_id)
    result = await db.execute(query)
    return [TaskRead.model_validate(t) for t in result.scalars().all()]
