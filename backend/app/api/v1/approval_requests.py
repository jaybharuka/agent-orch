"""Approval request (review queue) endpoints."""
import json
import uuid
from datetime import datetime, timezone
from uuid import UUID

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.dependencies import get_memory_manager
from app.config import settings
from app.schemas.approval_request import (
    ApprovalDecision,
    ApprovalRequestRead,
    EscalationContext,
)
from app.services import approval_request_service
from app.services.escalation_service import EscalationService


router = APIRouter()

CHAT_TTL_SECONDS = 48 * 60 * 60


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class ChatMessageCreate(BaseModel):
    role: str
    content: str


async def _get_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


async def _get_chat_messages(request_id: str) -> list[ChatMessage]:
    client = await _get_redis()
    try:
        key = f"chat:{request_id}"
        raw = await client.lrange(key, 0, -1)
        return [ChatMessage(**json.loads(m)) for m in raw]
    finally:
        await client.close()


async def _add_chat_message(request_id: str, payload: ChatMessageCreate) -> ChatMessage:
    client = await _get_redis()
    try:
        key = f"chat:{request_id}"
        message = ChatMessage(
            role=payload.role,
            content=payload.content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await client.rpush(key, message.model_dump_json())
        await client.expire(key, CHAT_TTL_SECONDS)
        return message
    finally:
        await client.close()


@router.get("/pending", response_model=list[ApprovalRequestRead])
async def list_pending_approval_requests(
    user_id: UUID | None = None, db: AsyncSession = Depends(get_db)
):
    """List pending approval requests for the UI queue."""
    return await approval_request_service.list_pending_approval_requests(db, user_id)


@router.get("/{request_id}", response_model=EscalationContext)
async def get_approval_request_context(request_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return the full escalation context needed by the review UI."""
    request = await approval_request_service.get_approval_request(db, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return EscalationContext(
        approval_request=request,
        proposed_action=request.proposed_action,
        agent_reasoning=request.agent_reasoning,
        context_snapshot=request.context_snapshot,
        relevant_memories=request.relevant_memories or [],
    )


@router.post("/{request_id}/decide", response_model=ApprovalRequestRead)
async def decide_approval_request(
    request_id: UUID,
    payload: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    memory_manager=Depends(get_memory_manager),
):
    """Submit a reviewer decision for an approval request."""
    request = await approval_request_service.get_approval_request(db, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="Approval request already resolved")
    escalation_service = EscalationService(
        memory_manager=memory_manager, db_session=db
    )
    reviewer_user_id = payload.reviewer_user_id or uuid.uuid4()
    return await escalation_service.resolve(request_id, payload, reviewer_user_id)


@router.get("/{request_id}/chat", response_model=list[ChatMessage])
async def get_chat(request_id: str):
    """Return chat messages for an approval request."""
    return await _get_chat_messages(request_id)


@router.post("/{request_id}/chat", response_model=list[ChatMessage])
async def post_chat(request_id: str, payload: ChatMessageCreate):
    """Add a chat message to an approval request thread."""
    await _add_chat_message(request_id, payload)
    return await _get_chat_messages(request_id)
