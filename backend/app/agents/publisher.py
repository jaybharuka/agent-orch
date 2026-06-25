"""Redis publishing helpers for agent events."""
import json

import redis.asyncio as redis

from app.config import settings


async def publish_status(user_id: str, task_id: str, status: str) -> None:
    """Publish a task status change to the user's approvals channel."""
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.publish(
                f"approvals:{user_id}",
                json.dumps(
                    {
                        "event": "task_status_changed",
                        "task_id": task_id,
                        "status": status,
                    }
                ),
            )
        finally:
            await client.close()
    except Exception:
        pass
