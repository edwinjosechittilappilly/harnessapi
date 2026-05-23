# Agentic RAG — harnessapi example

A complete, runnable agentic RAG system with **per-tenant document isolation** built on harnessapi + multi-tenancy. Each tenant gets their own vector store — documents ingested by one tenant are invisible to another.

```
POST /skills/ingest      ← chunk, embed, index a document
POST /skills/search      ← semantic search + GPT-4o answer
POST /skills/list_docs   ← list indexed documents for this tenant
GET  /mcp                ← all three skills as MCP tools
GET  /admin-mcp          ← skill variant management (admin only)
GET  /docs               ← Swagger UI
```

---

## Architecture

```
Client (curl / Claude Desktop / agent)
        │
        │  X-Tenant-ID: tenant-1          ← header identifies tenant
        ▼
┌─────────────────────────────────────────┐
│            harnessapi server            │
│                                         │
│  TenantContextMiddleware                │
│  (copies tenant_id → ContextVar)        │
│                 │                       │
│    ┌────────────┼────────────┐          │
│    ▼            ▼            ▼          │
│  ingest       search     list_docs      │
│    │            │                       │
│    ▼            ▼                       │
│  ChromaDB (rag_tenant-1)                │  ← isolated per tenant
│  ChromaDB (rag_tenant-2)                │  ← completely separate
└─────────────────────────────────────────┘
        │
        ▼  (search skill only)
    OpenAI GPT-4o (streaming answer)
```

**Embedding model:** `all-MiniLM-L6-v2` via sentence-transformers — runs locally, no API key needed for ingest.  
**Vector store:** ChromaDB — persisted to `./chroma_data/`, one collection per tenant.  
**Answer generation:** OpenAI GPT-4o — streaming tokens via SSE.  
**Variant storage:** SQLite (`./variants.db`) — persists skill customisations across restarts.

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An OpenAI API key

---

## Setup

### 1. Clone / navigate

```bash
cd examples/agentic-rag
```

### 2. Install dependencies

```bash
uv sync
```

Or with pip:

```bash
pip install -e .
```

### 3. Set environment variables

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...
```

Or export directly:

```bash
export OPENAI_API_KEY=sk-...
```

---

## Run

```bash
harnessapi run
# or: uvicorn main:app --reload
```

Server starts at `http://localhost:8000`. On first run, sentence-transformers downloads the embedding model (~90 MB). Subsequent starts are instant.

```
INFO: Started server process
INFO: Discovered skills: ingest, list_docs, search
INFO: MCP endpoint:   http://localhost:8000/mcp
INFO: Admin MCP:      http://localhost:8000/admin-mcp
INFO: Swagger UI:     http://localhost:8000/docs
```

---

## End-to-end walkthrough

### Step 1 — Ingest documents for tenant-1

```bash
curl -X POST http://localhost:8000/skills/ingest \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Tenant-ID: tenant-1" \
  -d '{
    "text": "The Apollo program was a series of space missions by NASA from 1961 to 1972. Apollo 11 landed the first humans on the Moon on July 20, 1969. Neil Armstrong and Buzz Aldrin walked on the lunar surface while Michael Collins orbited above. The mission used a Saturn V rocket, the most powerful ever built. Six Apollo missions successfully landed on the Moon.",
    "doc_id": "apollo-history",
    "metadata": {"title": "Apollo Program", "source": "history-book"}
  }'
```

Streaming response (SSE by default, JSON with `Accept: application/json`):

```json
{"chunks": [
  "Chunking document 'apollo-history'...",
  "Created 2 chunks (size=500, overlap=50)",
  "Embedding chunks...",
  "Indexed chunks 1–2 / 2",
  "Done. 2 chunks indexed for doc 'apollo-history' (tenant: tenant-1)"
]}
```

### Step 2 — Ingest a different document for tenant-2

```bash
curl -X POST http://localhost:8000/skills/ingest \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Tenant-ID: tenant-2" \
  -d '{
    "text": "The Great Barrier Reef is the world'\''s largest coral reef system, stretching over 2,300 kilometres off the coast of Queensland, Australia. It is home to over 1,500 species of fish, 4,000 types of mollusc, and 240 bird species. The reef is a UNESCO World Heritage Site and faces threats from climate change, ocean acidification, and crown-of-thorns starfish.",
    "doc_id": "great-barrier-reef",
    "metadata": {"title": "Great Barrier Reef", "source": "nature-encyclopedia"}
  }'
```

### Step 3 — Search tenant-1 (gets Apollo results only)

```bash
curl -X POST http://localhost:8000/skills/search \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Tenant-ID: tenant-1" \
  -d '{"query": "When did humans first land on the Moon?", "top_k": 3}'
```

Streaming SSE response (token by token from GPT-4o), or with `Accept: application/json`:

```json
{"chunks": [
  "Humans first landed on the Moon on **July 20, 1969**, during the Apollo 11 mission.",
  " Neil Armstrong and Buzz Aldrin descended to the lunar surface while Michael Collins",
  " remained in lunar orbit aboard the command module.\n\n",
  "---\nSources (1 documents):\n",
  "  • apollo-history (similarity: 0.921) — title: Apollo Program, source: history-book\n"
]}
```

### Step 4 — Verify tenant isolation

```bash
# tenant-2 searches for Apollo — no relevant docs, honest answer
curl -X POST http://localhost:8000/skills/search \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Tenant-ID: tenant-2" \
  -d '{"query": "When did humans first land on the Moon?"}'
```

Response: `"The context does not contain information about Moon landings..."` — tenant-2 only has reef data.

### Step 5 — List documents per tenant

```bash
# tenant-1
curl -X POST http://localhost:8000/skills/list_docs \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Tenant-ID: tenant-1" \
  -d '{}'
```

```json
{
  "tenant_id": "tenant-1",
  "document_count": 1,
  "total_chunks": 2,
  "documents": [
    {"doc_id": "apollo-history", "chunk_count": 2, "title": "Apollo Program", "source": "history-book"}
  ]
}
```

```bash
# tenant-2 — completely separate
curl -X POST http://localhost:8000/skills/list_docs \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Tenant-ID: tenant-2" \
  -d '{}'
```

```json
{
  "tenant_id": "tenant-2",
  "document_count": 1,
  "total_chunks": 3,
  "documents": [
    {"doc_id": "great-barrier-reef", "chunk_count": 3, "title": "Great Barrier Reef", "source": "nature-encyclopedia"}
  ]
}
```

### Step 6 — Streaming with SSE (default)

Drop the `Accept: application/json` header to receive live tokens:

```bash
curl -X POST http://localhost:8000/skills/search \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: tenant-1" \
  -d '{"query": "How many Moon landings were there?"}'
```

```
event: chunk
data: There were

event: chunk
data:  six successful

event: chunk
data:  Apollo Moon landings...

event: done
data:
```

---

## MCP tools — Claude Desktop / Claude Code

Add to your MCP client config:

```json
{
  "mcpServers": {
    "agentic-rag": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

All three skills appear as MCP tools: `ingest`, `search`, `list_docs`. The MCP server passes tenant headers through automatically if your client supports custom headers — or use the default `"default"` tenant for single-user setups.

Example Claude Desktop workflow:
1. *"Ingest this document: [paste text]"* → Claude calls `ingest`
2. *"What does the document say about X?"* → Claude calls `search`
3. *"What documents have I ingested?"* → Claude calls `list_docs`

---

## Admin MCP — manage skill variants as an agent

The admin MCP at `/admin-mcp` lets an agent (or you) customize how skills behave per-tenant without redeploying.

Add to your MCP config with the admin key:

```json
{
  "mcpServers": {
    "agentic-rag-admin": {
      "url": "http://localhost:8000/admin-mcp",
      "headers": {"X-Admin-Key": "dev-secret"}
    }
  }
}
```

### Customize the search skill for a tenant

```bash
# 1. Clone the search skill for tenant-1
curl -X POST http://localhost:8000/api/variants/tenant-1/search/clone \
  -H "X-Admin-Key: dev-secret"

# 2. Push a customized handler (e.g., use a different model or system prompt)
curl -X POST http://localhost:8000/api/variants/tenant-1/search/push \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: dev-secret" \
  -d '{"file": "handler.py", "content": "..."}'

# 3. Preview in sandbox — calls go through tenant variant, not prod
curl -X POST http://localhost:8000/api/variants/tenant-1/search/preview \
  -H "X-Admin-Key: dev-secret"

# 4. Promote once satisfied
curl -X POST http://localhost:8000/api/variants/tenant-1/search/promote \
  -H "X-Admin-Key: dev-secret"
```

After promotion, all calls from `tenant-1` to `/skills/search` run their customized handler. Other tenants are unaffected.

---

## Per-tenant sandbox execution

Provision an isolated execution environment for a tenant:

```bash
# Provision sandbox
curl -X POST http://localhost:8000/api/sandboxes/tenant-1/provision \
  -H "X-Admin-Key: dev-secret" \
  -d '{"skill": "search"}'

# Calls from tenant-1 now run in an isolated subprocess
curl -X POST http://localhost:8000/skills/search \
  -H "X-Tenant-ID: tenant-1" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"query": "Apollo mission details"}'
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key for the search skill |
| `OPENAI_MODEL` | `gpt-4o` | Model to use for answer generation |
| `CHROMA_PATH` | `./chroma_data` | Directory for ChromaDB persistence |
| `ADMIN_KEY` | `dev-secret` | Key required for `/admin-mcp` access |

---

## Architecture notes

**ContextVar pattern** — harnessapi injects `tenant_id` into `request.state` but skill handlers only receive the `Input` model. `TenantContextMiddleware` in `main.py` reads the tenant ID from `request.state` and copies it into a `ContextVar` before calling the handler. Each skill reads `tenant_id_var.get()` — no coupling to the request object, handlers stay testable.

**Collection-per-tenant** — ChromaDB collections are named `rag_{tenant_id}`. Isolation is enforced at the collection level; no cross-tenant query is possible. All collections share one `PersistentClient` backed by a single on-disk directory.

**Singleton embedder** — `sentence-transformers` loads the model once at first call and reuses it. The model stays in memory for the process lifetime — fast for high request rates.

**SQLite for variants** — `SQLiteStorageBackend` persists skill variants (customized handlers, sandbox state) across server restarts. For production, swap to a Postgres-backed custom `StorageBackend`.

**Re-ingest is idempotent** — the `ingest` handler deletes existing chunks for a `doc_id` before upserting new ones. Calling ingest twice with the same `doc_id` replaces, not duplicates.
