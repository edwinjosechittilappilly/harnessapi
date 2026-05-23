---
title: Streaming (SSE)
description: How harnessapi uses Server-Sent Events for streaming skill output — event format, JSON mode, Python and JavaScript clients, error handling, and timeouts.
---

harnessapi endpoints stream by default using **Server-Sent Events (SSE)**. The handler determines the protocol: `return` a value for a single response, `yield` values to stream progressively. The same endpoint, same URL, handles both.

---

## Why SSE by default

SSE is the right transport for LLM-powered skills. Language model output arrives token by token — buffering the entire response before sending it creates unnecessary latency and a poor user experience. SSE lets the client start rendering the first token while the rest are still generating.

SSE also suits any long-running computation that can produce incremental output: file processing, web scraping, multi-step reasoning. Clients receive progress as it happens rather than waiting for completion.

---

## Non-streaming — return a value

```python
async def handle(input: Input) -> Output:
    return Output(result=compute(input.text))
```

The client receives two events — the result, then a done signal:

```
event: result
data: {"result": "..."}

event: done
data:
```

---

## Streaming — yield chunks

Use an async generator. No return type annotation needed:

```python
async def handle(input: Input):
    async for token in llm.stream(input.prompt):
        yield token
```

Each yielded value becomes a `chunk` event. The `done` event is always the last:

```
event: chunk
data: The answer

event: chunk
data:  is

event: chunk
data:  42.

event: done
data:
```

---

## SSE event reference

| Event | When emitted | Data |
|-------|-------------|------|
| `chunk` | Each value yielded by a streaming handler | The yielded value as a string |
| `result` | Full JSON from a non-streaming handler | The Output model serialized to JSON |
| `done` | Always the last event | Empty |
| `error` | Handler raised an exception or timed out | Error message string |

---

## Switching to plain JSON

Add `Accept: application/json` — harnessapi collects all output and returns a standard HTTP response. No handler changes needed:

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

JSON mode output format:

- **Non-streaming handler** → Output model fields directly: `{"summary": "hello world", "word_count": 2}`
- **Streaming handler** → chunks collected into an array: `{"chunks": ["hello", " ", "world"]}`

---

## Real LLM streaming example

Using OpenAI-compatible streaming:

```python title="skills/chat/handler.py"
from openai import AsyncOpenAI
from .models import Input

client = AsyncOpenAI()

async def handle(input: Input):
    stream = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": input.prompt}],
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
```

The client receives each token as a `chunk` event as soon as the model produces it.

---

## Calling from Python

```python
import httpx

# SSE stream — process each chunk as it arrives
with httpx.Client() as client:
    with client.stream(
        "POST",
        "http://localhost:8000/skills/chat",
        json={"prompt": "What is 6 * 7?"},
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    print(chunk, end="", flush=True)

# JSON — block until complete
response = httpx.post(
    "http://localhost:8000/skills/chat",
    json={"prompt": "What is 6 * 7?"},
    headers={"Accept": "application/json"},
)
print(response.json())
```

---

## Calling from JavaScript

**Using `fetch` to read an SSE stream:**

```javascript
const response = await fetch("http://localhost:8000/skills/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "What is 6 * 7?" }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const text = decoder.decode(value);
  for (const line of text.split("\n")) {
    if (line.startsWith("data:")) {
      const chunk = line.slice(5).trim();
      if (chunk) process.stdout.write(chunk); // or update DOM
    }
  }
}
```

**Using the `EventSource` API** (GET-only, not suitable for POST with a body — use `fetch` above for POST skills):

```javascript
// Only works if your skill accepts GET — most harnessapi skills are POST
const source = new EventSource("http://localhost:8000/skills/status");
source.addEventListener("chunk", (e) => console.log(e.data));
source.addEventListener("done", () => source.close());
```

For POST-based skills (all harnessapi skill endpoints), use the `fetch` approach above.

---

## Error handling

Any exception raised by the handler emits an `error` event and closes the stream:

```python
async def handle(input: Input):
    if len(input.text) > 10000:
        raise ValueError("Input too long")
    yield process(input.text)
```

```
event: error
data: ValueError: Input too long

event: (stream closes)
```

In JSON mode (`Accept: application/json`), errors return an HTTP 500 with a JSON error body instead.

---

## Timeouts

Set per-skill in `skill.toml`:

```toml
[skill]
timeout_secs = 60   # default: 30
```

If the handler does not complete within the timeout, an `error` event is emitted:

```
event: error
data: Skill 'summarize' timed out after 60s

event: done
data:
```

In JSON mode, a timeout returns HTTP 504.

---

## See also

- [Skill folders](/harnessapi/concepts/skill-folders) — how handlers are discovered and loaded
- [MCP tools](/harnessapi/concepts/mcp) — how streaming handlers are handled in MCP (chunks are collected)
- [Examples](/harnessapi/examples/factorial) — real streaming skill implementation
