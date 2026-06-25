"""Review schemas."""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class ReviewSubmit(BaseModel):
    approved: bool
    feedback: str | None = None


class ReviewRead(BaseModel):
    id: UUID
    task_id: UUID
    status: str
    feedback: str | None
    approved: bool | None
    created_at: datetime
    resolved_at: datetime | None

    class Config:
        from_attributes = True
