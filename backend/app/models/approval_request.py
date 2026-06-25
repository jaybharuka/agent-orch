"""Approval request SQLAlchemy model."""
import uuid
from sqlalchemy import Column, String, DateTime, JSON, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    session_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)

    trigger = Column(
        String,
        nullable=False,
        comment="low_confidence, repeated_failure, sensitive_operation, low_reviewer_score, user_requested",
    )
    severity = Column(
        String,
        nullable=False,
        comment="notify, approve_action, approve_plan, take_over",
    )
    status = Column(String, default="pending", nullable=False)

    context_snapshot = Column(JSON, nullable=False)
    proposed_action = Column(Text, nullable=False)
    agent_reasoning = Column(Text, nullable=False)
    relevant_memories = Column(JSON, nullable=True)

    reviewer_user_id = Column(UUID(as_uuid=True), nullable=True)
    reviewer_decision = Column(String, nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    modified_plan = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
