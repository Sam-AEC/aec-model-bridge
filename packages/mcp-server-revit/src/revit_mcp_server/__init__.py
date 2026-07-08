"""AEC Model Bridge server entrypoint."""

from .mcp_server import run_mcp_server as run_server

__all__ = ["run_server"]
