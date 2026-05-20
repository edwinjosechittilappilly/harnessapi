# Streaming in harnessapi

## How it works

All skill endpoints use Server-Sent Events (SSE) by default. The handler type determines the event protocol:

**Non-streaming** — `return` a value:
```python
async def handle(input: Input) -> Output:
    return Output(result="done")
```
Client receives:
```
event: result
data: {"result": "done"}

event: done
data:
```

**Streaming** — `yield` chunks (async generator):
```python
async def handle(input: Input):
    for token in generate_tokens(input.prompt):
        yield token
```
Client receives:
```
event: chunk
data: Hello

event: chunk
data: world

event: done
data:
```

## SSE event protocol

| Event | When |
|-------|------|
| `chunk` | Each value yielded by a streaming handler |
| `result` | Complete JSON output from a non-streaming handler |
| `done` | Always the last event |
| `error` | Handler raised an exception |

## Calling from curl

```bash
# SSE stream (default)
curl -X POST http://localhost:8000/skills/my-skill \
  -H "Content-Type: application/json" \
  -d '{"field": "value"}'

# Plain JSON (no SSE)
curl -X POST http://localhost:8000/skills/my-skill \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"field": "value"}'
```

## Calling from Python

```python
import httpx

# SSE stream
with httpx.Client() as client:
    with client.stream("POST", "http://localhost:8000/skills/my-skill",
                        json={"field": "value"}) as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                print(line[5:].strip())

# JSON
r = httpx.post("http://localhost:8000/skills/my-skill",
               json={"field": "value"},
               headers={"Accept": "application/json"})
print(r.json())
```

## MCP and streaming

MCP tools are request-response. Streaming handlers are fully supported — harnessapi collects all yielded chunks and joins them as a single string response for MCP clients.

## Timeout

Set per-skill in `skill.toml`:
```toml
[skill]
timeout_secs = 60   # default: 30
```

Timeout applies to the full handler execution. On timeout, an `error` SSE event is emitted.
