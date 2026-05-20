---
name: factorial
description: Compute the factorial of a non-negative integer n, streaming each multiplication step. Use when asked to compute factorial, calculate n!, or demonstrate streaming math computation.
license: MIT
compatibility: Python 3.11+
---

## What this skill does

Computes `n!` iteratively, yielding each multiplication step as a streamed chunk so the client can observe the computation in progress.

## Input

- `n` — non-negative integer

## Output

Each step is streamed as a chunk:

```
start: 1
2: 2
3: 6
4: 24
5: 120
```

## Gotchas

- `n = 0` returns `0! = 1` immediately (by definition).
- Negative values raise `ValueError`.
- The handler is an async generator — each step is a separate SSE `chunk` event.
