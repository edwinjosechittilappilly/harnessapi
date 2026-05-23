"""Compute factorial of n, streaming each multiplication step."""
from .models import Input


async def handle(input: Input):
    if input.n < 0:
        raise ValueError("n must be a non-negative integer")
    acc = 1
    if input.n == 0:
        yield "0! = 1"
        return
    yield "start: 1"
    for i in range(2, input.n + 1):
        acc *= i
        yield f"{i}: {acc}"
