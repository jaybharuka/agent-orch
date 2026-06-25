"""FastAPI application entry point."""
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.router import api_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared services once at startup and clean up on shutdown."""
    from app.memory.memory_manager import MemoryManager
    from app.memory.working_memory import WorkingMemory
    from app.memory.long_term_memory import LongTermMemory
    from app.memory.postgres_memory_store import PostgresMemoryStore

    app.state.memory_manager = MemoryManager(
        working_memory=WorkingMemory(),
        long_term_memory=LongTermMemory(),
        postgres_store=PostgresMemoryStore(),
    )
    yield
    await app.state.memory_manager.close()


app = FastAPI(
    title="Agent Orchestration API",
    description="Supervisor → Specialist → Reviewer multi-agent orchestration",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://frontend:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    services: dict[str, str] = {}

    try:
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        services["redis"] = "ok"
    except Exception:
        services["redis"] = "degraded"

    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        services["postgres"] = "ok"
    except Exception:
        services["postgres"] = "degraded"

    try:
        async with httpx.AsyncClient(timeout=3.0) as http:
            resp = await http.get(f"{settings.chroma_url}/api/v2/heartbeat")
        services["chroma"] = "ok" if resp.status_code == 200 else "degraded"
    except Exception:
        services["chroma"] = "degraded"

    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": overall, "version": "1.0.0", "services": services}
