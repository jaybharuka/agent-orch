"""Short-term working memory layer backed by Redis."""
import json
from typing import Any

import redis.asyncio as redis

from app.config import settings


TTL_SECONDS = 24 * 60 * 60  # 24 hours


class WorkingMemoryError(Exception):
    """Raised when working memory operations fail due to Redis issues."""


class WorkingMemory:
    """Async Redis-backed scratchpad for task execution state."""

    def __init__(self) -> None:
        self._redis_url = settings.redis_url
        self._client: redis.Redis | None = None
        self._ttl = TTL_SECONDS

    async def _get_client(self) -> redis.Redis:
        """Return a connected Redis client, raising WorkingMemoryError on failure."""
        if self._client is None:
            try:
                self._client = redis.from_url(self._redis_url, decode_responses=True)
            except Exception as exc:
                raise WorkingMemoryError(
                    f"Failed to connect to Redis working memory at {self._redis_url}. "
                    f"Ensure Redis is running and REDIS_URL is configured. Error: {exc}"
                ) from exc
        return self._client

    async def _set(self, key: str, value: str) -> None:
        client = await self._get_client()
        try:
            await client.setex(key, self._ttl, value)
        except Exception as exc:
            raise WorkingMemoryError(
                f"Failed to write working memory key {key} to Redis: {exc}"
            ) from exc

    async def _get(self, key: str) -> str | None:
        client = await self._get_client()
        try:
            return await client.get(key)
        except Exception as exc:
            raise WorkingMemoryError(
                f"Failed to read working memory key {key} from Redis: {exc}"
            ) from exc

    async def _scan_keys(self, pattern: str) -> list[str]:
        client = await self._get_client()
        try:
            keys = []
            async for key in client.scan_iter(match=pattern):
                keys.append(key)
            return keys
        except Exception as exc:
            raise WorkingMemoryError(
                f"Failed to scan working memory keys matching {pattern}: {exc}"
            ) from exc

    async def save_plan(self, task_id: str, plan: list[dict]) -> None:
        """Store the execution plan as JSON."""
        key = f"task:{task_id}:plan:0"
        await self._set(key, json.dumps(plan))

    async def get_plan(self, task_id: str) -> list[dict]:
        """Retrieve the stored execution plan."""
        key = f"task:{task_id}:plan:0"
        value = await self._get(key)
        if value is None:
            return []
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkingMemoryError(
                f"Corrupted working memory plan for task {task_id}: {exc}"
            ) from exc

    async def save_output(self, task_id: str, subtask_id: str, output: str) -> None:
        """Store specialist output for a subtask."""
        key = f"task:{task_id}:output:{subtask_id}"
        await self._set(key, output)

    async def get_all_outputs(self, task_id: str) -> dict[str, str]:
        """Return all stored specialist outputs for a task."""
        pattern = f"task:{task_id}:output:*"
        keys = await self._scan_keys(pattern)
        outputs: dict[str, str] = {}
        client = await self._get_client()
        for key in keys:
            subtask_id = key.split(":")[-1]
            try:
                value = await client.get(key)
            except Exception as exc:
                raise WorkingMemoryError(
                    f"Failed to read working memory output {key}: {exc}"
                ) from exc
            if value is not None:
                outputs[subtask_id] = value
        return outputs

    async def save_intermediate(
        self, task_id: str, key: str, value: Any
    ) -> None:
        """Store generic scratch data as JSON."""
        redis_key = f"task:{task_id}:intermediate:{key}"
        await self._set(redis_key, json.dumps(value))

    async def get_intermediate(self, task_id: str, key: str) -> Any:
        """Retrieve generic scratch data."""
        redis_key = f"task:{task_id}:intermediate:{key}"
        value = await self._get(redis_key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkingMemoryError(
                f"Corrupted working memory intermediate value for task {task_id}, key {key}: {exc}"
            ) from exc

    async def save_error(
        self, task_id: str, subtask_id: str, error: str
    ) -> None:
        """Store an error entry for a subtask."""
        key = f"task:{task_id}:error:{subtask_id}"
        payload = json.dumps({"subtask_id": subtask_id, "error": error})
        await self._set(key, payload)

    async def get_errors(self, task_id: str) -> list[dict]:
        """Return all stored error entries for a task."""
        pattern = f"task:{task_id}:error:*"
        keys = await self._scan_keys(pattern)
        errors: list[dict] = []
        client = await self._get_client()
        for key in keys:
            try:
                value = await client.get(key)
            except Exception as exc:
                raise WorkingMemoryError(
                    f"Failed to read working memory error {key}: {exc}"
                ) from exc
            if value is not None:
                try:
                    errors.append(json.loads(value))
                except json.JSONDecodeError as exc:
                    raise WorkingMemoryError(
                        f"Corrupted working memory error for task {task_id}: {exc}"
                    ) from exc
        return errors

    async def clear_task(self, task_id: str) -> None:
        """Delete all working memory keys for a task."""
        pattern = f"task:{task_id}:*"
        keys = await self._scan_keys(pattern)
        if not keys:
            return
        client = await self._get_client()
        try:
            await client.delete(*keys)
        except Exception as exc:
            raise WorkingMemoryError(
                f"Failed to clear working memory for task {task_id}: {exc}"
            ) from exc

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            try:
                await self._client.close()
            finally:
                self._client = None
