"""ChromaDB long-term vector memory client."""
import chromadb
from app.config import settings


class ChromaMemoryClient:
    """Client for ChromaDB-backed vector memory."""

    def __init__(self) -> None:
        self.client = chromadb.HttpClient(host=settings.chroma_url)

    def query(self, query_text: str, top_k: int = 5) -> list[str]:
        """Query ChromaDB for memories relevant to the given text."""
        try:
            collection = self.client.get_or_create_collection("memory")
            results = collection.query(query_texts=[query_text], n_results=top_k)
            documents = results.get("documents", [[]])[0]
            return documents or []
        except Exception as exc:
            print(f"ChromaDB query failed: {exc}")
            return []
