"""Review business logic — delegates to approval_request_service."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.approval_request import ApprovalRequestRead
from app.services.approval_request_service import list_pending_approval_requests


async def list_pending_reviews(db: AsyncSession) -> list[ApprovalRequestRead]:
    return await list_pending_approval_requests(db)
