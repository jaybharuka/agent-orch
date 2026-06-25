"""Session schemas."""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class SessionCreate(BaseModel):
    title: str
    context: dict = Field(default_factory=dict)


class SessionRead(BaseModel):
    id: UUID
    title: str
    context: dict
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True
