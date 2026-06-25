"""LLM provider factory with OpenAI and stub fallback."""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake import FakeListChatModel
from langchain_openai import ChatOpenAI
from app.config import settings


def get_llm() -> BaseChatModel:
    """Return a chat model. Uses OpenAI if configured, otherwise a stub."""
    if settings.openai_api_key:
        return ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key)
    return FakeListChatModel(responses=["Stub LLM response: no OPENAI_API_KEY configured."])
