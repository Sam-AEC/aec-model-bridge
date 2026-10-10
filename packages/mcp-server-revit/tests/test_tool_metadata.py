"""The MCP tool listing must carry clear descriptions, documented parameters and annotations."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.workspace import WorkspaceMonitor


@pytest.fixture(scope="module")
def listed(tmp_path_factory):
    workspace_dir = Path(tmp_path_factory.mktemp("meta-ws"))
    registry, approval, job_manager, _modules, _ws = build_registry(WorkspaceMonitor([workspace_dir]))
    previous = (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager)
    mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = registry, approval, job_manager
    try:
        tools = asyncio.run(mcp_server.list_tools())
    finally:
        mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = previous
    gate_flags = {t.name: t for t in registry.get_all_tools()}
    return {t.name: t for t in tools}, gate_flags


def test_every_tool_has_all_four_annotations(listed):
    tools, _ = listed
    assert len(tools) > 150
    for tool in tools.values():
        ann = tool.annotations
        assert ann is not None, tool.name
        for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert getattr(ann, hint) is not None, f"{tool.name}: {hint} missing"
        assert ann.title, tool.name


def test_every_tool_has_a_substantial_description(listed):
    tools, _ = listed
    short = [t.name for t in tools.values() if len(t.description or "") < 40]
    assert short == []


def test_every_parameter_is_described(listed):
    tools, _ = listed
    missing = [
        f"{t.name}.{key}"
        for t in tools.values()
        for key, prop in t.inputSchema.get("properties", {}).items()
        if not (isinstance(prop, dict) and prop.get("description"))
    ]
    assert missing == []


def test_gated_tools_are_never_marked_read_only(listed):
    tools, gate = listed
    for name, tool in tools.items():
        if gate[name].is_mutating:
            assert tool.annotations.readOnlyHint is False, name
            assert "plan_id" in tool.inputSchema["properties"], name


def test_escape_hatches_are_destructive(listed):
    tools, gate = listed
    for name, tool in gate.items():
        if tool.destructive:
            assert tools[name].annotations.destructiveHint is True, name
    assert tools["revit_execute_python"].annotations.destructiveHint is True
    assert tools["rhino_run_python"].annotations.destructiveHint is True
    assert tools["revit_delete_element"].annotations.destructiveHint is True


def test_file_writing_and_plan_execution_tools_are_not_read_only(listed):
    tools, _ = listed
    for name in ("revit_export_ifc", "revit_export_dwg", "execute_plan", "plan_actions"):
        assert tools[name].annotations.readOnlyHint is False, name
    assert tools["execute_plan"].annotations.destructiveHint is True


def test_pure_readers_are_read_only_and_local_tools_are_closed_world(listed):
    tools, _ = listed
    for name in ("revit_list_levels", "revit_get_element_parameters", "ifc_get_metadata", "list_pending_plans"):
        ann = tools[name].annotations
        assert ann.readOnlyHint is True and ann.destructiveHint is False, name
        assert ann.openWorldHint is False, name
    assert tools["speckle_list_projects"].annotations.openWorldHint is True


def test_module_data_files_are_declared_as_package_data():
    """The wheel must ship module manifests, rules and recipes (non-Python files)."""
    import fnmatch
    import tomllib

    package_root = Path(__file__).resolve().parent.parent
    patterns = tomllib.loads((package_root / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "setuptools"
    ]["package-data"]["revit_mcp_server"]
    base = package_root / "src" / "revit_mcp_server"
    data_files = [
        p.relative_to(base).as_posix()
        for p in base.rglob("*")
        if p.is_file() and p.suffix in (".json", ".yaml") and "modules" in p.parts
    ]
    assert data_files
    uncovered = [f for f in data_files if not any(fnmatch.fnmatch(f, pat) for pat in patterns)]
    assert uncovered == []


def test_mcp_dependency_is_capped_below_2():
    import tomllib

    package_root = Path(__file__).resolve().parent.parent
    deps = tomllib.loads((package_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert any(d.replace(" ", "").startswith("mcp>=") and "<2" in d.replace(" ", "") for d in deps)


def test_provider_schema_is_not_mutated(listed):
    """Listing must not leak the added plan_id property back into the provider tool."""
    tools, gate = listed
    assert "plan_id" in tools["revit_create_wall"].inputSchema["properties"]
    assert "plan_id" not in gate["revit_create_wall"].input_schema.get("properties", {})
