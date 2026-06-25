"""Tool invocation SQLAlchemy model."""
import uuid
from sqlalchemy import Column, String, DateTime, JSON, Float, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class ToolInvocation(Base):
    __tablename__ = "tool_invocation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), nullable=True)
    subtask_id = Column(String, nullable=True)
    tool_name = Column(String, nullable=False)
    inputs = Column(JSON, default={})
    output = Column(JSON, nullable=True)
    latency_ms = Column(Float, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
