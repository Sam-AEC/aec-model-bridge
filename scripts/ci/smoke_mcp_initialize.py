#!/usr/bin/env python3
"""Start an MCP server over stdio, send one ``initialize`` and check the answer.

Standard library only, so it runs under any Python (the CI runner's, not the bundle's).
Everything after ``--`` is the command to start, for example:

    python scripts/ci/smoke_mcp_initialize.py -- C:\\other\\python\\python.exe -m revit_mcp_server
    python scripts/ci/smoke_mcp_initialize.py -- uv run python -m revit_mcp_server

MCP_REVIT_MODE defaults to ``mock`` so no Revit is needed. Exit code 0 means a valid
JSON-RPC ``initialize`` result (protocolVersion and serverInfo.name) came back in time.
Used to catch launchers that start fine on the build machine but not after the bundle is
moved (issue #159).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

PROTOCOL_VERSION = "2025-06-18"


def _read_response(proc: subprocess.Popen[bytes], request_id: int, timeout: float) -> dict[str, Any]:
    """Read stdout lines until the response to ``request_id`` arrives or time runs out."""
    result: list[dict[str, Any]] = []

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-protocol output; the check fails if nothing valid arrives
            if isinstance(message, dict) and message.get("id") == request_id:
                result.append(message)
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        thread.join(0.2)
    if not result:
        raise RuntimeError(
            f"no initialize response within {timeout:.0f}s"
            + (f" (process exited with code {proc.returncode})" if proc.poll() is not None else "")
        )
    return result[0]


def run(command: list[str], timeout: float) -> dict[str, Any]:
    env = dict(os.environ)
    env.setdefault("MCP_REVIT_MODE", "mock")
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    stderr_chunks: list[bytes] = []
    if proc.stderr is not None:
        stderr = proc.stderr
        threading.Thread(target=lambda: stderr_chunks.append(stderr.read()), daemon=True).start()
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "smoke-mcp-initialize", "version": "1"},
            },
        }
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        proc.stdin.flush()
        try:
            response = _read_response(proc, 1, timeout)
        except RuntimeError as exc:
            time.sleep(0.2)
            tail = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()[-2000:]
            raise RuntimeError(f"{exc}\nstderr: {tail or '(empty)'}") from exc
        if "error" in response:
            raise RuntimeError(f"initialize returned an error: {response['error']}")
        init = response.get("result")
        if not isinstance(init, dict) or not init.get("protocolVersion"):
            raise RuntimeError(f"initialize result has no protocolVersion: {response}")
        info = init.get("serverInfo")
        if not isinstance(info, dict) or not info.get("name"):
            raise RuntimeError(f"initialize result has no serverInfo.name: {response}")
        return init
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for the response (default 120)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- followed by the command to run")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the command to run after --")
    try:
        init = run(command, args.timeout)
    except (RuntimeError, OSError) as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        return 1
    info = init["serverInfo"]
    print(f"OK: {info.get('name')} {info.get('version', '')} protocol {init['protocolVersion']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
