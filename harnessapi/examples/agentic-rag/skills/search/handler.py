from __future__ import annotations

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AsyncOpenAI
from shared.context import tenant_id_var
from shared.store import get_collection
from shared.embedder import embed
from .models import Input

_openai = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai


async def handle(input: Input):
    tenant_id = tenant_id_var.get()
    collection = get_collection(tenant_id)

    count = collection.count()
    if count == 0:
        yield f"No documents indexed for tenant '{tenant_id}'. Ingest some documents first."
        return

    query_embedding = embed([input.query])[0]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(input.top_k, count),
        include=["documents", "metadatas", "distances"],
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    if not docs:
        yield "No relevant documents found for your query."
        return

    context_parts = []
    sources = []
    seen_docs = {}

    for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances)):
        doc_id = meta.get("doc_id", "unknown")
        chunk_idx = meta.get("chunk_index", "?")
        similarity = round(1 - dist, 3)

        context_parts.append(f"[Source {i + 1} — {doc_id}, chunk {chunk_idx}]\n{doc}")

        if doc_id not in seen_docs:
            seen_docs[doc_id] = True
            source_entry = {"doc_id": doc_id, "similarity": similarity}
            source_entry.update({k: v for k, v in meta.items() if k not in ("doc_id", "chunk_index")})
            sources.append(source_entry)

    context = "\n\n---\n\n".join(context_parts)
    system_prompt = (
        "You are a helpful assistant. Answer the user's question using only the provided context. "
        "If the context does not contain enough information to answer, say so clearly. "
        "Be concise and accurate."
    )
    user_message = f"Context:\n{context}\n\nQuestion: {input.query}"

    client = _get_openai()
    stream = await client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

    if input.include_sources and sources:
        yield f"\n\n---\nSources ({len(sources)} documents):\n"
        for s in sources:
            doc_id = s["doc_id"]
            sim = s["similarity"]
            extras = {k: v for k, v in s.items() if k not in ("doc_id", "similarity")}
            line = f"  • {doc_id} (similarity: {sim})"
            if extras:
                line += f" — {', '.join(f'{k}: {v}' for k, v in extras.items())}"
            yield line + "\n"
