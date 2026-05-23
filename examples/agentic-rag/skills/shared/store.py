import os
import chromadb

_client: chromadb.PersistentClient | None = None


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        path = os.environ.get("CHROMA_PATH", "./chroma_data")
        _client = chromadb.PersistentClient(path=path)
    return _client


def get_collection(tenant_id: str) -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=f"rag_{tenant_id}",
        metadata={"hnsw:space": "cosine"},
    )
