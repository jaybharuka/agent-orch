"""Task SQLAlchemy model."""
import uuid
from sqlalchemy import Column, String, DateTime, JSON, Text, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String, default="pending")
    plan_json = Column(JSON, nullable=True)
    final_output = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    reviewer_score = Column(Float, nullable=True)
    duration_ms = Column(Float, nullable=True)
    cost_usd = Column(Float, nullable=True)
    payload = Column(JSON, default={})
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
