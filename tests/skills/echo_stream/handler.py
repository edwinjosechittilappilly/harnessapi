"""Echo words one at a time (streaming)."""
from .models import Input


async def handle(input: Input):
    for word in input.text.split():
        yield word
