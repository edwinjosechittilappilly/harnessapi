"""Double the input value."""
from .models import Input, Output


async def handle(input: Input) -> Output:
    return Output(doubled=input.value * 2)
