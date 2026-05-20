---
title: Streaming (SSE)
description: How harnessapi uses Server-Sent Events for streaming skill output — and how to switch to plain JSON.
---

harnessapi endpoints stream by default using **Server-Sent Events (SSE)**. The handler type determines the protocol automatically.

## Non-streaming — return a value

```python
async def handle(input: Input) -> Output:
    return Output(result=compute(input.text))
```

Client receives:

```
event: result
data: {"result": "..."}

event: done
data:
```

## Streaming — yield chunks

Use an async generator. No return type annotation needed:

```python
async def handle(input: Input):
    async for token in llm.stream(input.prompt):
        yield token
```

Client receives:

```
event: chunk
data: The answer

event: chunk
data:  is 42.

event: done
data:
```

## SSE event protocol

| Event | When emitted |
|-------|-------------|
| `chunk` | Each value yielded by a streaming handler |
| `result` | Full JSON output from a non-streaming handler |
| `done` | Always the last event |
| `error` | Handler raised an exception or timed out |

## Switch to plain JSON

Add `Accept: application/json` to get a regular HTTP response instead of SSE. harnessapi collects all chunks and returns them together — no code changes needed:

```bash
# SSE (default)
curl -X POST http://localhost:8000/skills/summarize \
  -H "Content-Type: application/json" \
  -d '{"text": "hello world"}'

# Plain JSON
curl -X POST http://localhost:8000/skills/summarize \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"text": "hello world"}'
```

For **streaming** handlers, JSON mode returns `{"chunks": ["chunk1", "chunk2", ...]}`.

For **non-streaming** handlers, JSON mode returns the Output model fields directly:

```json
{"message": "Hello, world! Welcome to harnessapi.", "length": 36}
```

## Calling from Python

```python
import httpx

# SSE stream
with httpx.Client() as client:
    with client.stream("POST", "http://localhost:8000/skills/summarize",
                       json={"text": "hello world"}) as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                print(line[5:].strip())

# JSON
r = httpx.post(
    "http://localhost:8000/skills/summarize",
    json={"text": "hello world"},
    headers={"Accept": "application/json"},
)
print(r.json())
```

## Timeouts

Set per-skill in `skill.toml`:

```toml
[skill]
timeout_secs = 60   # default: 30
```

On timeout an `error` event is emitted:

```
event: error
data: Skill 'summarize' timed out after 60s
```

## Error handling

Any exception raised by the handler emits an `error` event and stops the stream:

```
event: error
data: ValueError: input too long

event: (stream ends)
```
