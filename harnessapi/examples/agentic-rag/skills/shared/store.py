from __future__ import annotations

import os
import chromadb

_client = None


def _get_client():
    global _client
    if _client is None:
        path = os.environ.get("CHROMA_PATH", "./chroma_data")
        _client = chromadb.PersistentClient(path=path)
    return _client


def get_collection(tenant_id: str):
    return _get_client().get_or_create_collection(
        name=f"rag_{tenant_id}",
        metadata={"hnsw:space": "cosine"},
    )
