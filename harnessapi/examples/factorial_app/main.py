from pathlib import Path

from harnessapi import HarnessAPI

app = HarnessAPI(
    skills_dir=Path(__file__).parent / "skills",
    title="Factorial Harness",
    description="Demo: factorial as a streaming skill + MCP tool",
)
