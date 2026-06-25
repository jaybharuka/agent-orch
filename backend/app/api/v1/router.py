"""API v1 router aggregator."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import redis.asyncio as redis
from app.api.v1 import approval_requests, tasks, sessions, memory
from app.config import settings

api_router = APIRouter()

api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(
    approval_requests.router, prefix="/reviews", tags=["reviews"]
)


@api_router.websocket("/ws/{user_id}")
async def websocket_reviews(websocket: WebSocket, user_id: str):
    """Push approval_required and task status events to connected clients."""
    await websocket.accept()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(f"approvals:{user_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(f"approvals:{user_id}")
        await pubsub.close()
        await client.close()
