"""Task endpoints."""
import json

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.config import settings
from app.schemas.task import TaskCreate, TaskRead
from app.services import task_service

router = APIRouter()


@router.get("/", response_model=list[TaskRead])
async def list_tasks(session_id: str | None = None, db: AsyncSession = Depends(get_db)):
    return await task_service.list_tasks(db, session_id=session_id)


@router.post("/", response_model=TaskRead)
async def create_task(payload: TaskCreate, db: AsyncSession = Depends(get_db)):
    return await task_service.create_task(db, payload)


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    return await task_service.get_task(db, task_id)


@router.post("/{task_id}/escalate")
async def escalate_task(task_id: str):
    """Request human intervention on a running task."""
    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.publish(
            f"task_control:{task_id}",
            json.dumps(
                {
                    "escalation_required": True,
                    "trigger": "user_requested",
                    "reason": "User requested escalation",
                }
            ),
        )
    finally:
        await client.close()
    return {"status": "escalation_requested", "task_id": task_id}
