"""Human-in-the-loop review endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dependencies import get_db
from app.schemas.review import ReviewSubmit, ReviewRead
from app.services import review_service

router = APIRouter()


@router.get("/pending", response_model=list[ReviewRead])
async def list_pending_reviews(db: AsyncSession = Depends(get_db)):
    return await review_service.list_pending_reviews(db)


@router.post("/{review_id}", response_model=ReviewRead)
async def submit_review(review_id: str, payload: ReviewSubmit, db: AsyncSession = Depends(get_db)):
    return await review_service.submit_review(db, review_id, payload)
