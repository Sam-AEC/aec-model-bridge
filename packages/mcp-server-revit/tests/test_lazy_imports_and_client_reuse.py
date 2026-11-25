"""Regression tests: heavy imports stay lazy and the bridge client is reused."""

from __future__ import annotations

import subprocess
import sys

import httpx

from revit_mcp_server.bridge import client as client_module
from revit_mcp_server.bridge.client import BridgeClient

HEAVY = ("specklepy", "ifcopenshell", "networkx")


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_importing_mcp_server_does_not_pull_heavy_modules():
    code = (
        "import sys, revit_mcp_server.mcp_server\n"
        f"heavy = [m for m in {HEAVY!r} if m in sys.modules]\n"
        "print(','.join(heavy))\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    result = _run(code)
    assert result.returncode == 0, f"heavy modules imported at startup: {result.stdout.strip()} {result.stderr[-500:]}"


def test_importing_provider_package_does_not_pull_heavy_modules():
    code = (
        "import sys, revit_mcp_server.providers\n"
        "import revit_mcp_server.providers.cloud, revit_mcp_server.providers.ifc\n"
        "import revit_mcp_server.providers.graph, revit_mcp_server.providers.semantic_provider\n"
        "import revit_mcp_server.providers.identity_mapper\n"
        "from revit_mcp_server.providers.graph import SemanticGraphProvider\n"
        "SemanticGraphProvider().get_capabilities()\n"
        f"heavy = [m for m in {HEAVY!r} if m in sys.modules]\n"
        "print(','.join(heavy))\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    result = _run(code)
    assert result.returncode == 0, f"heavy modules imported by providers: {result.stdout.strip()} {result.stderr[-500:]}"


def _patched_bridge(monkeypatch, token=None):
    created: list[httpx.Client] = []
    real_init = httpx.Client.__init__
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"ok": True, "data": {"seen": request.headers.get("authorization")}}
        )
    )

    class Counting(httpx.Client):
        def __init__(self, *args, **kwargs):
            real_init(self, *args, transport=transport, **kwargs)
            created.append(self)

    monkeypatch.setattr(client_module.httpx, "Client", Counting)
    return BridgeClient("http://bridge.test", token=token), created


def test_client_is_reused_across_calls(monkeypatch):
    bridge, created = _patched_bridge(monkeypatch, token="t1")
    for _ in range(5):
        assert bridge.call_tool("x", {})["seen"] == "Bearer t1"
    assert len(created) == 1
    bridge.close()


def test_client_rebuilt_when_token_changes_and_closed_on_close(monkeypatch):
    bridge, created = _patched_bridge(monkeypatch, token="t1")
    bridge.call_tool("x", {})
    bridge.token = "t2"
    assert bridge.call_tool("x", {})["seen"] == "Bearer t2"
    assert len(created) == 2
    assert created[0].is_closed
    bridge.close()
    assert created[1].is_closed
    bridge.call_tool("x", {})
    assert len(created) == 3
    bridge.close()


# Loaded by module code only when a tool needs them (report_generator, qaqc_checker, recipe_runner).
STARTUP_LAZY = ("openpyxl", "numpy", "yaml")


def test_building_the_registry_does_not_pull_lazy_modules_or_open_http_clients(tmp_path):
    code = (
        "import os, sys, httpx\n"
        f"os.environ.update(MCP_REVIT_MODE='mock', MCP_REVIT_WORKSPACE_DIR={str(tmp_path)!r},\n"
        f"                  MCP_REVIT_ALLOWED_DIRECTORIES={str(tmp_path)!r})\n"
        "made = []\n"
        "real = httpx.AsyncClient.__init__\n"
        "def counting(self, *a, **k):\n"
        "    made.append(1)\n"
        "    real(self, *a, **k)\n"
        "httpx.AsyncClient.__init__ = counting\n"
        "from revit_mcp_server.registry_factory import build_registry\n"
        "build_registry()\n"
        f"heavy = [m for m in {HEAVY + STARTUP_LAZY!r} if m in sys.modules]\n"
        "print(','.join(heavy), len(made))\n"
        "sys.exit(1 if heavy or made else 0)\n"
    )
    result = _run(code)
    assert result.returncode == 0, f"loaded at registry build: {result.stdout.strip()} {result.stderr[-800:]}"


def test_cloud_provider_builds_its_http_client_on_first_use_and_closes_it():
    import asyncio

    from revit_mcp_server.providers.cloud import SpeckleProvider

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    provider = SpeckleProvider(transport=transport, oauth_transport=transport)
    assert provider._client_obj is None and provider.oauth._client_obj is None
    client = provider._client
    assert isinstance(client, httpx.AsyncClient) and provider._client is client
    asyncio.run(provider.shutdown())
    assert client.is_closed and provider._client_obj is None


def test_report_generator_still_writes_excel_after_lazy_import():
    import importlib.util
    from pathlib import Path

    import revit_mcp_server

    path = Path(revit_mcp_server.__file__).parent / "modules" / "report_generator" / "module.py"
    spec = importlib.util.spec_from_file_location("_rg_lazy_check", path)
    rg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rg)
    wb = rg._workbook()
    ws = wb.active
    rg._write_header(ws, ["Name", "Value"])
    assert ws.cell(row=1, column=1).font.bold is True
    assert ws.cell(row=1, column=2).fill.fgColor.rgb.endswith("2C5F8A")


def test_bridge_client_asks_for_gzip_and_decodes_it(monkeypatch):
    import gzip
    import json

    seen = {}
    big = {"ok": True, "data": {"elements": [{"id": i, "name": f"Wall {i}"} for i in range(500)]}}

    def handler(request):
        seen["accept_encoding"] = request.headers.get("accept-encoding")
        body = gzip.compress(json.dumps(big).encode())
        seen["wire_bytes"] = len(body)
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(body))

    real_init = httpx.Client.__init__

    class Gz(httpx.Client):
        def __init__(self, *args, **kwargs):
            real_init(self, *args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(client_module.httpx, "Client", Gz)
    bridge = BridgeClient("http://bridge.test", token="t")
    result = bridge.call_tool("revit.list_elements", {})
    assert seen["accept_encoding"] == "gzip"
    assert len(result["elements"]) == 500
    assert seen["wire_bytes"] < len(json.dumps(big))
    bridge.close()


def test_bridge_client_still_reads_plain_bodies(monkeypatch):
    bridge, _ = _patched_bridge(monkeypatch, token="t")
    assert bridge.call_tool("x", {})["seen"] == "Bearer t"
    bridge.close()
