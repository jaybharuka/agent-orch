"""Agent schemas."""
from pydantic import BaseModel


class AgentRunRequest(BaseModel):
    task_id: str
    session_id: str
