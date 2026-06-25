"""Review business logic."""
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.review import ReviewSubmit, ReviewRead


async def list_pending_reviews(db: AsyncSession) -> list[ReviewRead]:
    raise NotImplementedError


async def submit_review(db: AsyncSession, review_id: str, payload: ReviewSubmit) -> ReviewRead:
    raise NotImplementedError
