"""Redis short-term memory client."""
import redis
from app.config import settings


class RedisClient:
    """Client for Redis-backed short-term memory."""

    def __init__(self) -> None:
        self.client = redis.from_url(settings.redis_url)
