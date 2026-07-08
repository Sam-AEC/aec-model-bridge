"""Loopback-only HTTP shim for the Revit dockable panel (WebView2 JS).

The MCP hub (mcp_server.py) speaks stdio to AI clients (Claude Desktop/Code) —
a browser page in WebView2 cannot launch or speak to a stdio subprocess. Per
docs/product/PLUGIN_APP_ARCHITECTURE.md §2 ("panel UI is HTML/JS talking to
the add-in over the WebView2 message bridge, and to the hub via localhost"),
this module runs the *same* provider registry as the stdio server behind a
minimal local-only HTTP server, so the C# add-in can forward panel button
clicks to real MCP tools.

This is not a general-purpose remote API: it binds 127.0.0.1 only, mirroring
every other switch in this product (Revit/Rhino/Navisworks bridges), and
exists purely so a WebView2 page in the same machine's Revit process can
reach the hub.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from .errors import RevitMCPError
from .registry_factory import build_registry
from .security.audit import redact_data

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8787


def _run_tool_sync(registry, approval_provider, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one tool call to completion in a fresh event loop.

    Mirrors the approval-gate check and post-execution plan-state transition
    that mcp_server.py's call_tool() applies, so a tool called through the
    panel is gated identically to one called through MCP.
    """
    async def _run() -> Dict[str, Any]:
        provider = registry.lookup_tool_provider(name)
        if not provider:
            raise ValueError(f"Unknown tool '{name}'")

        tool_def = registry.lookup_tool(name)
        if tool_def and tool_def.is_mutating:
            approval_provider.gate.check_tool_execution(name, arguments)

        result = await provider.execute_tool(name, arguments)

        if tool_def and tool_def.is_mutating and isinstance(arguments, dict) and "plan_id" in arguments:
            try:
                approval_provider.gate.update_plan_state(arguments["plan_id"], "executed")
            except Exception:
                pass

        return result

    return asyncio.run(_run())


class PanelRequestHandler(BaseHTTPRequestHandler):
    registry = None
    approval_provider = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("panel_server: " + format, *args)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "healthy", "tools": len(self.registry.get_all_tools())})
            return
        self._send_json(404, {"ok": False, "error": f"Unknown path '{self.path}'"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/execute":
            self._send_json(404, {"ok": False, "error": f"Unknown path '{self.path}'"})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Request body must be valid JSON"})
            return

        tool = body.get("tool")
        arguments = body.get("arguments", {})
        if not tool or not isinstance(tool, str):
            self._send_json(400, {"ok": False, "error": "Request body must include a string 'tool' field"})
            return

        try:
            result = _run_tool_sync(self.registry, self.approval_provider, tool, arguments)
            self._send_json(200, {"ok": True, "result": redact_data(result)})
        except RevitMCPError as e:
            self._send_json(409, {"ok": False, "error": redact_data(str(e))})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": redact_data(str(e))})


def build_server(port: int | None = None) -> ThreadingHTTPServer:
    registry, approval_provider, _job_manager, _module_registry, _workspace = build_registry()

    handler = type("BoundPanelRequestHandler", (PanelRequestHandler,), {
        "registry": registry,
        "approval_provider": approval_provider,
    })

    resolved_port = port if port is not None else int(os.getenv("MCP_PANEL_HTTP_PORT", str(DEFAULT_PORT)))
    server = ThreadingHTTPServer(("127.0.0.1", resolved_port), handler)
    return server


def run_panel_server() -> None:
    """Entry point for running the panel HTTP shim as a standalone process."""
    server = build_server()
    logger.info("Panel HTTP shim listening on http://127.0.0.1:%d", server.server_address[1])
    try:
        server.serve_forever()
    finally:
        server.shutdown()


if __name__ == "__main__":
    run_panel_server()
