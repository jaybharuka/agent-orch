"""Human-in-the-loop review endpoints."""
import json
from uuid import UUID

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.config import settings
from app.schemas.approval_request import (
    ApprovalDecision,
    ApprovalRequestRead,
    EscalationContext,
)
from app.services.approval_request_service import (
    get_approval_request,
    list_pending_approval_requests,
    submit_approval_decision,
)

router = APIRouter()


@router.get("/pending", response_model=list[ApprovalRequestRead])
async def list_pending_reviews(db: AsyncSession = Depends(get_db)):
    return await list_pending_approval_requests(db)


@router.get("/{review_id}", response_model=EscalationContext)
async def get_review_detail(review_id: UUID, db: AsyncSession = Depends(get_db)):
    request = await get_approval_request(db, review_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return EscalationContext(
        approval_request=request,
        proposed_action=request.proposed_action,
        agent_reasoning=request.agent_reasoning,
        context_snapshot=request.context_snapshot,
        relevant_memories=request.relevant_memories or [],
    )


@router.post("/{review_id}/decide", response_model=ApprovalRequestRead)
async def submit_decision(
    review_id: UUID,
    payload: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
):
    request = await get_approval_request(db, review_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    resolved = await submit_approval_decision(db, review_id, payload)
    # Publish to Redis so _wait_for_resolution in the graph unblocks.
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        await client.publish(
            f"approval_resolved:{review_id}",
            json.dumps({
                "event": "approval_resolved",
                "request_id": str(review_id),
                "decision": payload.decision,
            }),
        )
        await client.aclose()
    except Exception:
        pass
    return resolved


@router.get("/{review_id}/chat")
async def get_chat_messages(review_id: UUID):
    return []


@router.post("/{review_id}/chat")
async def send_chat_message(review_id: UUID, message: dict):
    return []
