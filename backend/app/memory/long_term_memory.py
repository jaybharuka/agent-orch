"""Long-term semantic memory layer backed by ChromaDB."""
import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

from app.config import settings


ChromaClient = Any


TASK_COLLECTION = "task_results"
FACT_COLLECTION = "facts"
RECENCY_DECAY_DAYS = 30
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class LongTermMemoryError(Exception):
    """Raised when long-term memory operations fail due to ChromaDB issues."""


@dataclass
class MemoryEntry:
    """A retrieved long-term memory entry."""

    id: str
    task_description: str
    summary: str
    tools_used: list[str]
    reviewer_score: float
    created_at: str
    tags: list[str]
    importance_score: float


class _MiniLMEmbeddingFunction:
    """ChromaDB-compatible embedding function using all-MiniLM-L6-v2."""

    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None

    def __call__(self, input: list[str]) -> list[list[float]]:
        if self._model is None:
            self._model = SentenceTransformer(EMBEDDING_MODEL)
        embeddings = self._model.encode(input, show_progress_bar=False)
        return embeddings.tolist()


class LongTermMemory:
    """Async ChromaDB-backed semantic memory for tasks and facts."""

    def __init__(self) -> None:
        self._chroma_url = settings.chroma_url
        self._client: ChromaClient | None = None
        self._embedding_function = _MiniLMEmbeddingFunction()

    def _get_client(self) -> ChromaClient:
        """Return a connected ChromaDB HTTP client."""
        if self._client is None:
            try:
                self._client = chromadb.HttpClient(host=self._chroma_url)
            except Exception as exc:
                raise LongTermMemoryError(
                    f"Failed to connect to ChromaDB long-term memory at {self._chroma_url}. "
                    f"Ensure ChromaDB is running and CHROMA_URL is configured. Error: {exc}"
                ) from exc
        return self._client

    def _get_collection(self, name: str):
        """Get or create a ChromaDB collection with the MiniLM embedding function."""
        client = self._get_client()
        try:
            return client.get_or_create_collection(
                name=name,
                embedding_function=self._embedding_function,
            )
        except Exception as exc:
            raise LongTermMemoryError(
                f"Failed to access ChromaDB collection {name}: {exc}"
            ) from exc

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous ChromaDB call in a thread."""
        return await asyncio.to_thread(func, *args, **kwargs)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _compute_importance_score(reviewer_score: float, created_at: str) -> float:
        """Combine reviewer score with a recency decay over 30 days."""
        try:
            created_dt = datetime.fromisoformat(created_at)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            created_dt = datetime.now(timezone.utc)

        age_seconds = (datetime.now(timezone.utc) - created_dt).total_seconds()
        age_days = max(0.0, age_seconds / 86400)
        recency_weight = exp(-age_days / RECENCY_DECAY_DAYS)
        return round(reviewer_score * 0.6 + recency_weight * 0.4, 4)

    @staticmethod
    def _make_summary(final_output: str, max_length: int = 500) -> str:
        if len(final_output) <= max_length:
            return final_output
        return final_output[:max_length].rsplit(" ", 1)[0] + "..."

    @staticmethod
    def _serialize_list(value: list[str]) -> str:
        return json.dumps(value)

    @staticmethod
    def _deserialize_list(value: str) -> list[str]:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []

    async def store_task_result(
        self,
        task_id: str,
        user_id: str,
        task_description: str,
        final_output: str,
        tools_used: list[str],
        reviewer_score: float,
        tags: list[str],
    ) -> str:
        """Embed and store a completed task result."""
        memory_id = str(uuid.uuid4())
        created_at = self._now_iso()
        importance_score = self._compute_importance_score(reviewer_score, created_at)
        summary = self._make_summary(final_output)

        def _store():
            collection = self._get_collection(TASK_COLLECTION)
            collection.add(
                ids=[memory_id],
                documents=[task_description],
                metadatas=[
                    {
                        "task_id": task_id,
                        "user_id": user_id,
                        "task_description": task_description,
                        "summary": summary,
                        "tools_used": self._serialize_list(tools_used),
                        "reviewer_score": reviewer_score,
                        "created_at": created_at,
                        "tags": self._serialize_list(tags),
                        "importance_score": importance_score,
                    }
                ],
            )
            return memory_id

        return await self._run_sync(_store)

    async def retrieve_similar(
        self, query: str, user_id: str, n: int = 5
    ) -> list[MemoryEntry]:
        """Semantic search for similar past tasks scoped to a user."""
        def _query():
            collection = self._get_collection(TASK_COLLECTION)
            return collection.query(
                query_texts=[query],
                n_results=n,
                where={"user_id": user_id},
            )

        results = await self._run_sync(_query)
        return self._results_to_entries(results)

    async def store_fact(
        self, user_id: str, fact: str, source: str, importance: float
    ) -> str:
        """Store a domain fact or user preference."""
        memory_id = str(uuid.uuid4())
        created_at = self._now_iso()

        def _store():
            collection = self._get_collection(FACT_COLLECTION)
            collection.add(
                ids=[memory_id],
                documents=[fact],
                metadatas=[
                    {
                        "user_id": user_id,
                        "source": source,
                        "importance": importance,
                        "created_at": created_at,
                    }
                ],
            )
            return memory_id

        return await self._run_sync(_store)

    async def retrieve_facts(self, query: str, user_id: str, n: int = 3) -> list[str]:
        """Semantic search for facts scoped to a user."""
        def _query():
            collection = self._get_collection(FACT_COLLECTION)
            return collection.query(
                query_texts=[query],
                n_results=n,
                where={"user_id": user_id},
            )

        results = await self._run_sync(_query)
        documents = results.get("documents", [[]])[0]
        return documents or []

    async def delete_entry(self, memory_id: str) -> None:
        """Hard delete a memory entry from either collection."""
        def _delete_from(name: str) -> bool:
            collection = self._get_collection(name)
            try:
                collection.delete(ids=[memory_id])
                return True
            except Exception:
                return False

        task_deleted = await self._run_sync(_delete_from, TASK_COLLECTION)
        fact_deleted = await self._run_sync(_delete_from, FACT_COLLECTION)

        if not task_deleted and not fact_deleted:
            raise LongTermMemoryError(
                f"Memory entry {memory_id} not found in any collection"
            )

    async def list_entries(self, user_id: str, limit: int = 50) -> list[MemoryEntry]:
        """Return memory dashboard entries for a user."""
        def _list():
            collection = self._get_collection(TASK_COLLECTION)
            return collection.get(
                where={"user_id": user_id},
                limit=limit,
                include=["metadatas"],
            )

        results = await self._run_sync(_list)
        entries: list[MemoryEntry] = []
        ids = results.get("ids", [])
        metadatas = results.get("metadatas", [])
        for memory_id, metadata in zip(ids, metadatas):
            if not isinstance(metadata, dict):
                continue
            created_at = metadata.get("created_at", self._now_iso())
            reviewer_score = metadata.get("reviewer_score", 0.0)
            entries.append(
                MemoryEntry(
                    id=memory_id,
                    task_description=metadata.get("task_description", ""),
                    summary=metadata.get("summary", ""),
                    tools_used=self._deserialize_list(metadata.get("tools_used", "[]")),
                    reviewer_score=reviewer_score,
                    created_at=created_at,
                    tags=self._deserialize_list(metadata.get("tags", "[]")),
                    importance_score=self._compute_importance_score(
                        reviewer_score, created_at
                    ),
                )
            )
        return entries

    def _results_to_entries(self, results: dict) -> list[MemoryEntry]:
        """Convert a ChromaDB query result into MemoryEntry objects."""
        entries: list[MemoryEntry] = []
        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        for memory_id, metadata in zip(ids, metadatas):
            if not isinstance(metadata, dict):
                continue
            created_at = metadata.get("created_at", self._now_iso())
            reviewer_score = metadata.get("reviewer_score", 0.0)
            entries.append(
                MemoryEntry(
                    id=memory_id,
                    task_description=metadata.get("task_description", ""),
                    summary=metadata.get("summary", ""),
                    tools_used=self._deserialize_list(metadata.get("tools_used", "[]")),
                    reviewer_score=reviewer_score,
                    created_at=created_at,
                    tags=self._deserialize_list(metadata.get("tags", "[]")),
                    importance_score=self._compute_importance_score(
                        reviewer_score, created_at
                    ),
                )
            )
        return entries

    async def close(self) -> None:
        """Reset the client connection; ChromaDB HTTP clients are stateless."""
        self._client = None
