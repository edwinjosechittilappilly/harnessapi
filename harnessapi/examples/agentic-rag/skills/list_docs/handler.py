import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.context import tenant_id_var
from shared.store import get_collection
from .models import Input, Output


async def handle(input: Input) -> Output:
    tenant_id = tenant_id_var.get()
    collection = get_collection(tenant_id)

    total_chunks = collection.count()

    if total_chunks == 0:
        return Output(
            tenant_id=tenant_id,
            document_count=0,
            total_chunks=0,
            documents=[],
        )

    all_items = collection.get(include=["metadatas"])
    metadatas = all_items["metadatas"] or []

    docs: dict[str, dict] = {}
    for meta in metadatas:
        doc_id = meta.get("doc_id", "unknown")
        if doc_id not in docs:
            base = {k: v for k, v in meta.items() if k not in ("doc_id", "chunk_index")}
            docs[doc_id] = {"doc_id": doc_id, "chunk_count": 0, **base}
        docs[doc_id]["chunk_count"] += 1

    documents = sorted(docs.values(), key=lambda d: d["doc_id"])

    return Output(
        tenant_id=tenant_id,
        document_count=len(documents),
        total_chunks=total_chunks,
        documents=documents,
    )
