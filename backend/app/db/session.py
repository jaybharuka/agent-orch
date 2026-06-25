"""Database session management."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

engine = create_async_engine(settings.database_url, future=True, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
