from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from revit_mcp_server.bridge.client import BridgeClient as HubBridgeClient
from revit_mcp_server.config import BridgeMode, Config
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers import ApprovalProvider, ProviderRegistry, RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor


REPO_ROOT = Path(__file__).resolve().parents[4]
TESTS_DIR = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPO_ROOT / "scripts" / "revit" / "generate_canonical_test_model.py"
QAQC_MODULE_PATH = (
    REPO_ROOT
    / "packages"
    / "mcp-server-revit"
    / "src"
    / "revit_mcp_server"
    / "modules"
    / "qaqc_checker"
    / "module.py"
)
SNAPSHOT_GOLDEN = REPO_ROOT / "fixtures" / "canonical-model" / "goldens" / "snapshot-summary.json"
QAQC_GOLDEN = REPO_ROOT / "fixtures" / "canonical-model" / "goldens" / "qaqc-findings-summary.json"

pytestmark = pytest.mark.e2e


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_canonical_test_model", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_mcp_server_class():
    spec = importlib.util.spec_from_file_location("test_helpers", TESTS_DIR / "helpers.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.MCPServer


def load_qaqc_module():
    spec = importlib.util.spec_from_file_location("qaqc_checker_module", QAQC_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.QaqcCheckerModule()


@pytest.fixture(scope="session")
def bridge_switch():
    if os.getenv("AEC_MODEL_BRIDGE_E2E") != "1":
        pytest.skip("Set AEC_MODEL_BRIDGE_E2E=1 and open the canonical model in Revit.")

    generator = load_generator()
    url = os.getenv("AEC_MODEL_BRIDGE_REVIT_URL") or os.getenv("MCP_REVIT_BRIDGE_URL")
    token = os.getenv("AEC_MODEL_BRIDGE_REVIT_TOKEN") or os.getenv("MCP_REVIT_BRIDGE_TOKEN")
    switch = generator.discover_switch(url, token)
    try:
        generator.BridgeClient(switch, timeout=5).get("/health")
    except generator.BridgeCallError as exc:
        pytest.skip(f"Revit bridge is not reachable: {exc}")
    return switch


def test_mutating_tools_require_approved_plan(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    registry = ProviderRegistry()
    approval = ApprovalProvider(workspace=workspace, registry=registry, approval_mode="required")
    registry.register(approval)
    registry.register(RevitProvider(workspace=workspace, mode=BridgeMode.mock))

    tool_def = registry.lookup_tool("revit_create_wall")
    assert tool_def is not None
    assert tool_def.is_mutating

    with pytest.raises(BridgeError, match="requires a valid 'plan_id'"):
        approval.gate.check_tool_execution(tool_def.name, {})

    plan = approval.gate.create_plan(
        [{"tool": tool_def.name, "arguments": {"start_x": 0, "end_x": 10}}],
        [{"status": "before-state-captured"}],
    )
    with pytest.raises(BridgeError, match="not 'approved'"):
        approval.gate.check_tool_execution(tool_def.name, {"plan_id": plan["plan_id"]})

    approval.gate.update_plan_state(plan["plan_id"], "approved")
    approval.gate.check_tool_execution(tool_def.name, {"plan_id": plan["plan_id"]})


def test_hub_reaches_revit_addin(bridge_switch, tmp_path):
    server_cls = load_mcp_server_class()
    cfg = Config(
        workspace_dir=tmp_path,
        allowed_directories=[tmp_path],
        audit_log=tmp_path / "audit.log",
        bridge_url=bridge_switch.endpoint,
        mode=BridgeMode.bridge,
    )
    server = server_cls(
        config=cfg,
        bridge_factory=lambda url, token=None: HubBridgeClient(url, token=token or bridge_switch.token),
    )
    try:
        response = server.handle_tool("revit_health", {"request_id": "e2e-health"})
    finally:
        server.shutdown()

    assert response
    assert response.get("status", "healthy") not in {"error", "unhealthy"}


def test_canonical_snapshot_and_qaqc_goldens(bridge_switch, tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RevitProvider(
        workspace=workspace,
        mode=BridgeMode.bridge,
        bridge_url=bridge_switch.endpoint,
        bridge_factory=lambda url, token=None: HubBridgeClient(url, token=token or bridge_switch.token),
    )

    result = asyncio.run(provider.execute_tool("revit_extract_snapshot", {"dirty_only": False}))
    snapshot_path = Path(result.get("path", ""))
    if not snapshot_path.exists():
        pytest.skip(f"Bridge returned inaccessible snapshot path: {snapshot_path}")

    snapshot = load_json(snapshot_path)
    snapshot_id = snapshot["snapshot_id"]
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir(exist_ok=True)
    (snapshots_dir / f"{snapshot_id}.json").write_text(json.dumps(snapshot), encoding="utf-8")

    snapshot_golden = load_json(SNAPSHOT_GOLDEN)
    counts = Counter(element.get("category") for element in snapshot.get("elements", []))
    for category, expected in snapshot_golden["required_category_counts"].items():
        assert counts[category] == expected
    assert len(snapshot.get("elements", [])) >= snapshot_golden["minimum_element_count"]

    qaqc = load_qaqc_module().run_check(
        snapshot_id=snapshot_id,
        rule_pack=load_json(QAQC_GOLDEN)["rule_pack"],
        workspace=workspace,
    )
    actual = Counter(finding["rule_id"] for finding in qaqc["findings"])
    expected = load_json(QAQC_GOLDEN)["seeded_rule_counts"]
    assert {rule_id: actual[rule_id] for rule_id in expected} == expected
