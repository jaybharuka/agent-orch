"""Session endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dependencies import get_db
from app.schemas.session import SessionCreate, SessionRead
from app.services import session_service

router = APIRouter()


@router.get("/", response_model=list[SessionRead])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    return await session_service.list_sessions(db)


@router.post("/", response_model=SessionRead)
async def create_session(payload: SessionCreate, db: AsyncSession = Depends(get_db)):
    return await session_service.create_session(db, payload)


@router.get("/{session_id}", response_model=SessionRead)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    return await session_service.get_session(db, session_id)
