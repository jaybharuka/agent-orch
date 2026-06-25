"""Memory SQLAlchemy model."""
import uuid
from sqlalchemy import Column, String, DateTime, JSON, Text, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    memory_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    importance_score = Column(Float, nullable=True)
    tags = Column(JSON, nullable=True)
    metadata_ = Column("metadata", JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
