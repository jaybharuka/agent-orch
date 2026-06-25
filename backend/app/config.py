"""Application configuration."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"
    secret_key: str = "changeme-in-production"
    database_url: str = "postgresql+asyncpg://agentorch:agentorch@localhost:5432/agentorch"
    redis_url: str = "redis://localhost:6379/0"
    chroma_url: str = "http://localhost:8010"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.1-70b-instruct"
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
