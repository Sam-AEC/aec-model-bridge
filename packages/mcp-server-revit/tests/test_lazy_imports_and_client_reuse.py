"""Regression tests: heavy imports stay lazy and the bridge client is reused."""

from __future__ import annotations

import json
import subprocess
import sys

import httpx
import pytest

from revit_mcp_server.bridge import client as client_module
from revit_mcp_server.bridge.client import BridgeClient

HEAVY = ("specklepy", "ifcopenshell", "networkx")


# Loaded by module code only when a tool needs them (report_generator, qaqc_checker, recipe_runner).
STARTUP_LAZY = ("openpyxl", "numpy", "yaml")

# One fresh interpreter walks through every import-time stage and records which
# forbidden modules are loaded after each one. Each stage only adds imports, so a
# module that leaks at an earlier stage is still reported at that stage.
_PROBE = """
import json, os, sys, tempfile
import httpx

tmp = tempfile.mkdtemp()
os.environ.update(MCP_REVIT_MODE='mock', MCP_REVIT_WORKSPACE_DIR=tmp, MCP_REVIT_ALLOWED_DIRECTORIES=tmp)
heavy, lazy = {heavy!r}, {lazy!r}
made = []
real = httpx.AsyncClient.__init__
def counting(self, *a, **k):
    made.append(1)
    real(self, *a, **k)
httpx.AsyncClient.__init__ = counting

def loaded(names):
    return [m for m in names if m in sys.modules]

out = {{}}
import revit_mcp_server.mcp_server
out['mcp_server'] = loaded(heavy)

import revit_mcp_server.providers
import revit_mcp_server.providers.cloud, revit_mcp_server.providers.ifc
import revit_mcp_server.providers.graph, revit_mcp_server.providers.semantic_provider
import revit_mcp_server.providers.identity_mapper
from revit_mcp_server.providers.graph import SemanticGraphProvider
SemanticGraphProvider().get_capabilities()
out['providers'] = loaded(heavy)

from revit_mcp_server.registry_factory import build_registry
build_registry()
out['registry'] = loaded(heavy + lazy)
out['registry_http_clients'] = len(made)
print('PROBE ' + json.dumps(out))
"""


@pytest.fixture(scope="module")
def import_probe() -> dict:
    code = _PROBE.format(heavy=HEAVY, lazy=STARTUP_LAZY)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"import probe failed: {result.stderr[-800:]}"
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("PROBE "))
    return json.loads(line[len("PROBE "):])


def test_importing_mcp_server_does_not_pull_heavy_modules(import_probe):
    assert import_probe["mcp_server"] == [], f"heavy modules imported at startup: {import_probe['mcp_server']}"


def test_importing_provider_package_does_not_pull_heavy_modules(import_probe):
    assert import_probe["providers"] == [], f"heavy modules imported by providers: {import_probe['providers']}"


def test_building_the_registry_does_not_pull_lazy_modules_or_open_http_clients(import_probe):
    assert import_probe["registry"] == [], f"loaded at registry build: {import_probe['registry']}"
    assert import_probe["registry_http_clients"] == 0


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
