import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.context import tenant_id_var
from shared.store import get_collection
from shared.embedder import embed
from .models import Input


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += chunk_size - overlap
    return chunks


async def handle(input: Input):
    tenant_id = tenant_id_var.get()
    collection = get_collection(tenant_id)

    yield f"Chunking document '{input.doc_id}'..."

    chunks = _chunk_text(input.text, input.chunk_size, input.chunk_overlap)
    total = len(chunks)
    yield f"Created {total} chunks (size={input.chunk_size}, overlap={input.chunk_overlap})"

    # Remove any existing chunks for this doc_id before reinserting
    try:
        existing = collection.get(where={"doc_id": input.doc_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
            yield f"Replaced {len(existing['ids'])} existing chunks for '{input.doc_id}'"
    except Exception:
        pass

    yield "Embedding chunks..."
    embeddings = embed(chunks)

    ids = [f"{input.doc_id}__chunk_{i}" for i in range(total)]
    metadatas = [
        {"doc_id": input.doc_id, "chunk_index": str(i), **input.metadata}
        for i in range(total)
    ]

    batch_size = 50
    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        collection.upsert(
            ids=ids[batch_start:batch_end],
            embeddings=embeddings[batch_start:batch_end],
            documents=chunks[batch_start:batch_end],
            metadatas=metadatas[batch_start:batch_end],
        )
        yield f"Indexed chunks {batch_start + 1}–{batch_end} / {total}"

    yield f"Done. {total} chunks indexed for doc '{input.doc_id}' (tenant: {tenant_id})"
