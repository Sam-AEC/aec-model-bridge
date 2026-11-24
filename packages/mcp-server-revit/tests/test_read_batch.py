"""Read batches (#277): several add-in reads in one Revit turn, never a write.

The add-in side (revit.batch, BridgeBatch.cs) is covered by packages/revit-bridge-addin-tests.
UNVERIFIED in live Revit: the latency gain of a batch is not measured here.
"""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path

import httpx
import pytest

from revit_mcp_server.bridge.client import BATCH_COMMAND, MAX_BATCH_COMMANDS, BridgeClient
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError, CommandFailed
from revit_mcp_server.providers.revit import BATCH_EXCLUDED, BATCH_SIDE_EFFECT_COMMANDS, RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import is_read_only_tool


# --------------------------------------------------------------------------- #
# Bridge client
# --------------------------------------------------------------------------- #
class BatchAddin:
    """Answers /execute for revit.batch like the C# command: one entry per member, in order."""

    def __init__(self, results=None, gzip_body: bool = False) -> None:
        self.bodies: list[dict] = []
        self.results = results
        self.gzip_body = gzip_body

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        commands = body["payload"]["commands"]
        results = self.results if self.results is not None else [
            {"index": i, "tool": c["tool"], "ok": True, "result": {"echo": c["payload"], "wall_id": 5}}
            for i, c in enumerate(commands)
        ]
        envelope = {"Status": "ok", "Tool": body["tool"], "Result": {"batch": True, "count": len(results), "results": results}}
        if self.gzip_body:
            raw = gzip.compress(json.dumps(envelope).encode())
            return httpx.Response(200, content=raw, headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
        return httpx.Response(200, json=envelope)


def client_for(addin: BatchAddin, catalog=None) -> BridgeClient:
    client = BridgeClient("http://bridge.test", timeout=30, token="tok")
    client._http = httpx.Client(transport=httpx.MockTransport(addin.handler))
    client._http_key = (client.token, client.timeout)
    client._tool_catalog = catalog
    return client


def test_client_sends_one_batch_and_returns_results_in_order():
    addin = BatchAddin()
    client = client_for(addin, catalog=[BATCH_COMMAND, "revit.list_levels"])
    out = client.call_batch([{"tool": "revit.list_levels"}, {"tool": "revit.get_element_geometry", "payload": {"element_id": 3}}])
    assert len(addin.bodies) == 1
    assert addin.bodies[0]["tool"] == BATCH_COMMAND
    assert addin.bodies[0]["payload"]["commands"] == [
        {"tool": "revit.list_levels", "payload": {}},
        {"tool": "revit.get_element_geometry", "payload": {"element_id": 3}},
    ]
    assert out[1]["echo"] == {"element_id": 3}
    assert out[0]["element_id"] == 5, "element id normalisation applies to each member"


def test_client_reports_a_failed_member_without_failing_the_others():
    addin = BatchAddin(results=[
        {"index": 0, "tool": "revit.a", "ok": True, "result": {"x": 1}},
        {"index": 1, "tool": "revit.b", "ok": False, "error": "Element 9 not found", "result": None},
    ])
    out = client_for(addin, catalog=[BATCH_COMMAND]).call_batch([{"tool": "revit.a"}, {"tool": "revit.b"}])
    assert out[0] == {"x": 1}
    assert isinstance(out[1], CommandFailed) and "Element 9 not found" in str(out[1])


def test_client_refuses_nesting_oversize_and_bad_members_before_sending():
    addin = BatchAddin()
    client = client_for(addin, catalog=[BATCH_COMMAND])
    with pytest.raises(ValueError, match="nested"):
        client.call_batch([{"tool": BATCH_COMMAND, "payload": {"commands": []}}])
    with pytest.raises(ValueError, match="at most 25"):
        client.call_batch([{"tool": "revit.list_levels"}] * (MAX_BATCH_COMMANDS + 1))
    with pytest.raises(ValueError, match="payload"):
        client.call_batch([{"tool": "revit.list_levels", "payload": [1]}])
    with pytest.raises(ValueError, match="tool name"):
        client.call_batch([{"payload": {}}])
    assert addin.bodies == []
    assert client.call_batch([]) == []


def test_client_fails_closed_on_a_result_that_does_not_match_the_request():
    addin = BatchAddin(results=[{"index": 0, "tool": "revit.a", "ok": True, "result": {}}])
    with pytest.raises(BridgeError, match="does not match"):
        client_for(addin, catalog=[BATCH_COMMAND]).call_batch([{"tool": "revit.a"}, {"tool": "revit.b"}])


def test_supports_batch_follows_the_addin_catalog():
    assert client_for(BatchAddin(), catalog=[BATCH_COMMAND]).supports_batch() is True
    assert client_for(BatchAddin(), catalog=["revit.list_levels"]).supports_batch() is False
    assert client_for(BatchAddin(), catalog=None).supports_batch() is False


def test_gzip_responses_from_the_addin_are_decoded():
    """BridgeServer gzips bodies over 64 KB when asked; httpx asks and decodes on its own."""
    addin = BatchAddin(gzip_body=True)
    client = client_for(addin, catalog=[BATCH_COMMAND])
    big = {"names": ["x" * 100] * 1000}
    out = client.call_batch([{"tool": "revit.a", "payload": big}])
    assert out[0]["echo"] == big
    request = httpx.Request("GET", "http://bridge.test/health")
    assert "gzip" in client._get_client().build_request("GET", request.url).headers.get("accept-encoding", "")


# --------------------------------------------------------------------------- #
# Provider: only read-only tools may be batched
# --------------------------------------------------------------------------- #
class RecordingBridge:
    """A live bridge that supports revit.batch and records what reaches it."""

    def __init__(self, supports: bool = True, fail_batch: Exception | None = None) -> None:
        self.supports = supports
        self.fail_batch = fail_batch
        self.single: list[tuple[str, dict]] = []
        self.batches: list[list[dict]] = []

    def supports_batch(self) -> bool:
        return self.supports

    def _answer(self, name: str, payload: dict) -> dict:
        if name == "revit.get_document_info":
            return {"title": "Villa", "path": "C:/models/Villa.rvt"}
        if name == "revit.get_element_geometry":
            return {"success": True, "element_id": payload["element_id"], "length": 10.0}
        if name == "revit.get_parameter_value":
            return {**payload, "value": "3048 mm"}
        return {"ok_for": name}

    def send_tool(self, name: str, payload: dict) -> dict:
        self.single.append((name, payload))
        return self._answer(name, payload)

    def call_batch(self, commands: list[dict]) -> list:
        self.batches.append(commands)
        if self.fail_batch is not None:
            raise self.fail_batch
        return [self._answer(c["tool"], c["payload"]) for c in commands]


def make_provider(tmp_path, bridge=None):
    bridge = bridge or RecordingBridge()
    prov = RevitProvider(
        workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge,
        bridge_url="http://127.0.0.1:1", bridge_factory=lambda *args: bridge,
    )
    return prov, bridge


def _sample_args(name: str) -> dict:
    return {"element_id": 1} if "element" in name else {}


def test_every_tool_that_is_not_read_only_is_refused(tmp_path):
    prov, bridge = make_provider(tmp_path)
    refused, allowed = [], []
    for tool in prov.get_capabilities():
        reason = prov.batch_refusal(tool.name, {})
        (refused if reason else allowed).append(tool.name)
        if not is_read_only_tool(tool.name, tool) or tool.name in BATCH_EXCLUDED:
            assert reason, f"{tool.name} must not be batchable"
    assert allowed, "some read tools should be batchable"
    assert {"revit_get_element_geometry", "revit_get_parameter_value", "revit_get_document_info"} <= set(allowed)
    for name in ("revit_create_wall", "revit_delete_element", "revit_execute_python", "revit_raw_command",
                 "revit_render_3d", "revit_reflect_get", "revit_save_document"):
        assert name in refused, name
    assert bridge.single == [] and bridge.batches == []


def test_side_effect_commands_are_refused_like_the_addin_does(tmp_path):
    # Mirrors BridgeBatch.HasSideEffects in the add-in: read-only by flag, but they write files,
    # open a transaction, change the selection or view, or reset the dirty tracker.
    prov, _ = make_provider(tmp_path)
    for tool in prov.get_capabilities():
        command = prov._tool_mapping.get(tool.name, (None,))[0]
        if isinstance(command, str) and (command.startswith("revit.export_") or command in BATCH_SIDE_EFFECT_COMMANDS):
            assert prov.batch_refusal(tool.name, {}), f"{tool.name} ({command}) must not be batchable"
    for name in ("revit_extract_snapshot", "revit_get_snapshot_delta", "revit_clear_preview"):
        if name in prov._tool_mapping:
            assert prov.batch_refusal(name, {}), name
    addin = (Path(__file__).resolve().parents[2] / "revit-bridge-addin" / "src" / "Bridge" / "BridgeBatch.cs").read_text(encoding="utf-8")
    for command in BATCH_SIDE_EFFECT_COMMANDS:
        assert f'"{command}"' in addin, f"{command} must be refused by the add-in as well"
    assert 'StartsWith("revit.export_"' in addin


@pytest.mark.parametrize("bad", [
    ("revit_create_wall", {"start_x": 0}),
    ("revit_delete_element", {"element_id": 1}),
    ("revit_execute_python", {"code": "print(1)", "mode": "read"}),
    ("revit_raw_command", {"command": "revit.create_wall"}),
    ("revit.create_wall", {}),
    ("revit_no_such_tool", {}),
    ("revit_list_elements", {"limit": 5}),
    ("revit_get_document_info", "not a dict"),
])
def test_one_write_or_unknown_member_refuses_the_whole_batch(tmp_path, bad):
    prov, bridge = make_provider(tmp_path)
    calls = [("revit_get_document_info", {}), bad]
    with pytest.raises(ValueError, match="Read batch refused"):
        asyncio.run(prov.execute_read_batch(calls))
    assert bridge.single == [] and bridge.batches == [], "nothing is sent when one member is refused"


def test_reads_go_in_groups_of_25_and_come_back_in_order(tmp_path):
    prov, bridge = make_provider(tmp_path)
    calls = [("revit_get_element_geometry", {"element_id": i}) for i in range(1, 31)]
    out = asyncio.run(prov.execute_read_batch(calls))
    assert [len(b) for b in bridge.batches] == [25, 5]
    assert all(c["tool"] == "revit.get_element_geometry" for b in bridge.batches for c in b)
    assert [r["element_id"] for r in out] == list(range(1, 31))
    assert bridge.single == []


def test_without_addin_support_reads_run_one_by_one(tmp_path):
    prov, bridge = make_provider(tmp_path, RecordingBridge(supports=False))
    out = asyncio.run(prov.execute_read_batch([("revit_get_document_info", {}), ("revit_get_element_geometry", {"element_id": 2})]))
    assert bridge.batches == []
    assert [name for name, _ in bridge.single] == ["revit.get_document_info", "revit.get_element_geometry"]
    assert out[1]["element_id"] == 2


def test_a_failed_group_is_reported_per_member(tmp_path):
    prov, bridge = make_provider(tmp_path, RecordingBridge(fail_batch=BridgeError("lost contact")))
    out = asyncio.run(prov.execute_read_batch([("revit_get_document_info", {}), ("revit_list_levels", {})]))
    assert all(isinstance(r, BridgeError) for r in out)


def test_mock_mode_runs_reads_one_by_one(tmp_path):
    prov = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    out = asyncio.run(prov.execute_read_batch([("revit_list_levels", {})]))
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# revit_inspect_elements uses the batch
# --------------------------------------------------------------------------- #
def test_inspection_batches_its_reads_with_the_same_result(tmp_path):
    batched_prov, batched = make_provider(tmp_path)
    single_prov, single = make_provider(tmp_path, RecordingBridge(supports=False))
    args = {"element_ids": list(range(1, 11)), "parameter_names": ["Mark", "Length"], "expected_document_title": "Villa"}

    with_batch = asyncio.run(batched_prov.execute_tool("revit_inspect_elements", dict(args)))
    without = asyncio.run(single_prov.execute_tool("revit_inspect_elements", dict(args)))

    assert with_batch == without
    assert with_batch["success"] is True
    # The opening document guard is one read; the 30 element sections and the closing document read
    # go in two batches instead of 31 separate Revit turns.
    assert [name for name, _ in batched.single] == ["revit.get_document_info"]
    assert [len(b) for b in batched.batches] == [25, 6]
    assert batched.batches[-1][-1]["tool"] == "revit.get_document_info"
    order = [c["tool"] for b in batched.batches for c in b]
    assert order == [name for name, _ in single.single[1:]], "same reads in the same order"


def test_inspection_skips_the_batch_when_the_document_guard_fails(tmp_path):
    prov, bridge = make_provider(tmp_path)
    result = asyncio.run(prov.execute_tool("revit_inspect_elements", {"element_ids": [1], "expected_document_title": "Other"}))
    assert result["document"]["guard_error"] == "DOCUMENT_TITLE_MISMATCH"
    assert bridge.batches == []


def test_inspection_reports_a_failed_batch_as_failed_sections(tmp_path):
    prov, _ = make_provider(tmp_path, RecordingBridge(fail_batch=BridgeError("lost contact")))
    result = asyncio.run(prov.execute_tool("revit_inspect_elements", {"element_ids": [1, 2]}))
    assert result["success"] is False
    assert result["completeness"]["failed_sections"] == 2
    assert result["elements"][0]["geometry"]["exception_type"] == "BridgeError"
    assert result["document"]["unchanged_at_endpoints"] is False
