"""Session business logic."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.models.session import Session
from app.schemas.session import SessionCreate, SessionRead


async def create_session(db: AsyncSession, payload: SessionCreate) -> SessionRead:
    session = Session(title=payload.title, context=payload.context)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return SessionRead.model_validate(session)


async def get_session(db: AsyncSession, session_id: str) -> SessionRead:
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionRead.model_validate(session)


async def list_sessions(db: AsyncSession) -> list[SessionRead]:
    result = await db.execute(select(Session).order_by(Session.created_at.desc()))
    return [SessionRead.model_validate(s) for s in result.scalars().all()]
