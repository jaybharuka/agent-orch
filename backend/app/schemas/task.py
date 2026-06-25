"""Task schemas."""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class TaskCreate(BaseModel):
    session_id: UUID
    payload: dict = Field(default_factory=dict)


class TaskRead(BaseModel):
    id: UUID
    session_id: UUID
    status: str
    payload: dict
    result: dict | None
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True
