"""Minimal harnessapi skill runner for use inside per-tenant sandbox processes.

Invoked as:
    python -m harnessapi.multitenancy.sandbox_runner --port 34521 --skills-dir /tmp/sandbox-user-a

The process exits when stdin is closed (parent controls lifetime via pipe).
edit endpoints are enabled so the central server can push variant handlers.
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path


def _watch_stdin_and_exit() -> None:
    """Exit when stdin closes — signals that the parent process is gone."""
    sys.stdin.read()
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="harnessapi sandbox runner")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--skills-dir", type=str, required=True)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    # Watch stdin — exit when parent closes the pipe
    t = threading.Thread(target=_watch_stdin_and_exit, daemon=True)
    t.start()

    import uvicorn
    from harnessapi import HarnessAPI

    app = HarnessAPI(
        skills_dir=Path(args.skills_dir),
        enable_edit_endpoints=True,  # central server pushes variants via EditRoute
        title="Sandbox Skill Runner",
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
