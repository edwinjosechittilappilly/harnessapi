"""Greet someone by name."""
from .models import Input, Output


async def handle(input: Input) -> Output:
    return Output(message=f"Hello, {input.name}!")
