"""Static MCP profiles hide discovery and refuse dispatch without weakening approval."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.base import AECProvider, ProviderTool
from revit_mcp_server.providers.module_provider import ModuleProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.providers.revit_jobs import RevitJobProvider
from revit_mcp_server.jobs import JobManager
from revit_mcp_server.security.dispatch import gate_before, run_gated_tool
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_profiles import ToolProfile, ToolProfileBlocked, load_tool_profile


def tool(name, module_id=None, mutating=False):
    return ProviderTool(name=name, module_id=module_id, description="test",
                        inputSchema={"type": "object"}, is_mutating=mutating)


class FakeProvider(AECProvider):
    def __init__(self, identity, tools):
        self.identity, self.tools, self.calls = identity, tools, []

    def get_identity(self):
        return self.identity

    def get_capabilities(self):
        return self.tools

    async def execute_tool(self, name, arguments):
        self.calls.append(name)
        return {"ok": True}

    async def check_health(self):
        return {"status": "healthy"}

    async def shutdown(self):
        pass


def registry_with(*providers):
    registry = ProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return registry


def test_default_full_preserves_discovery_and_dispatch(monkeypatch):
    provider = FakeProvider("rhino", [tool("odd_alias", "revit_mep", True)])
    registry = registry_with(provider)
    registry.freeze_tool_profile(load_tool_profile({}))
    assert [t.name for t in registry.get_all_tools()] == ["odd_alias"]
    assert registry.lookup_tool_provider("odd_alias") is provider
    assert registry.lookup_tool("odd_alias").is_mutating
    monkeypatch.setattr(mcp_server, "registry", registry)
    assert [t.name for t in asyncio.run(mcp_server.list_tools())] == ["odd_alias"]


def test_daily_matches_provider_and_manifest_ids_not_tool_prefixes():
    registry = registry_with(
        FakeProvider("module", [tool("unrelated_alias", "revit_mep"),
                                tool("rhino_named_but_retained", "revit_docs"),
                                tool("custom_ifc_alias", "revit_ifc")]),
        FakeProvider("speckle_cloud", [tool("unprefixed_cloud")]),
        FakeProvider("revit", [tool("revit_execute_python", mutating=True)]),
    )
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "daily"}))
    assert {t.name for t in registry.get_all_tools()} == {"rhino_named_but_retained", "revit_execute_python"}
    with pytest.raises(ToolProfileBlocked, match="profile 'daily'"):
        registry.lookup_tool("unrelated_alias")


def test_custom_globs_match_either_identity_and_exclusion_wins(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"include": ["revit", "revit_d*"], "exclude": ["revit_docs"]}))
    registry = registry_with(
        FakeProvider("revit", [tool("native")]),
        FakeProvider("module", [tool("doc_alias", "revit_docs"), tool("detail_alias", "revit_details"),
                                tool("param_alias", "revit_params")]),
    )
    registry.freeze_tool_profile(load_tool_profile({
        "MCP_REVIT_TOOL_PROFILE": "custom", "MCP_REVIT_TOOL_PROFILE_FILE": str(path)}))
    assert {t.name for t in registry.get_all_tools()} == {"native", "detail_alias"}


def test_exclude_only_file_and_daily_builtin_exclusion_win(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"exclude": ["revit_docs"]}))
    profile = load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "daily", "MCP_REVIT_TOOL_PROFILE_FILE": str(path)})
    assert profile.allows("module", "revit_params")
    assert not profile.allows("module", "revit_docs")
    assert not profile.allows("module", "revit_mep")


@pytest.mark.parametrize("value", ["", "DAILY", "invalid", " daily "])
def test_invalid_profile_fails(value):
    with pytest.raises(ValueError, match="MCP_REVIT_TOOL_PROFILE"):
        load_tool_profile({"MCP_REVIT_TOOL_PROFILE": value})


def test_custom_requires_file_and_missing_or_empty_files_fail(tmp_path):
    for env in ({"MCP_REVIT_TOOL_PROFILE": "custom"},
                {"MCP_REVIT_TOOL_PROFILE_FILE": ""},
                {"MCP_REVIT_TOOL_PROFILE_FILE": str(tmp_path / "missing.json")}):
        with pytest.raises(ValueError, match="MCP_REVIT_TOOL_PROFILE"):
            load_tool_profile(env)


@pytest.mark.parametrize("content", ["not json", "[]", '{"tools":["revit_get_context"]}',
                                    '{"include":"revit"}', '{"exclude":[1]}',
                                    '{"include":[""]}', '{"include":[" revit"]}',
                                    '{"exclude":null}'])
def test_invalid_files_fail_instead_of_silently_using_full(tmp_path, content):
    path = tmp_path / "profile.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="profile|PROFILE"):
        load_tool_profile({"MCP_REVIT_TOOL_PROFILE_FILE": str(path)})


def test_invalid_settings_fail_before_server_startup(monkeypatch):
    monkeypatch.setenv("MCP_REVIT_TOOL_PROFILE", "invalid")
    monkeypatch.setattr(mcp_server, "build_registry", lambda: pytest.fail("providers constructed before validation"))
    with pytest.raises(ValueError, match="MCP_REVIT_TOOL_PROFILE"):
        asyncio.run(mcp_server.main())


def test_snapshot_does_not_reconsult_file_env_or_provider_capabilities(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    path.write_text('{"exclude":["revit_mep"]}')
    monkeypatch.setenv("MCP_REVIT_TOOL_PROFILE", "custom")
    monkeypatch.setenv("MCP_REVIT_TOOL_PROFILE_FILE", str(path))
    provider = FakeProvider("revit", [tool("hidden", "revit_mep"), tool("visible")])
    registry = registry_with(provider)
    registry.freeze_tool_profile(load_tool_profile())
    path.write_text('{}')
    monkeypatch.setenv("MCP_REVIT_TOOL_PROFILE", "full")
    provider.tools.append(tool("late_added"))
    provider.tools[1].is_mutating = True
    assert [t.name for t in registry.get_all_tools()] == ["visible"]
    assert not registry.lookup_tool("visible").is_mutating
    assert registry.lookup_tool("late_added") is None
    with pytest.raises(ToolProfileBlocked):
        registry.lookup_tool_provider("hidden")
    with pytest.raises(RuntimeError, match="static"):
        registry.freeze_tool_profile(ToolProfile())
    with pytest.raises(RuntimeError, match="frozen"):
        registry.register(FakeProvider("late", []))


@pytest.mark.parametrize("run_async", [False, True])
def test_hidden_write_refused_before_claim_execution_or_queue(monkeypatch, run_async):
    provider = FakeProvider("module", [tool("hidden_write", "revit_mep", True)])
    registry = registry_with(provider)
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "daily"}))
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(
        gate=SimpleNamespace(claim_action=lambda *a: pytest.fail("hidden action claimed"))))
    monkeypatch.setattr(mcp_server, "job_manager", SimpleNamespace(
        submit=lambda *a, **kw: pytest.fail("hidden action queued")))
    result = asyncio.run(mcp_server.call_tool("hidden_write", {"run_async": run_async}))
    assert result.isError
    assert result.structuredContent["error"]["kind"] == "tool_profile_blocked"
    assert "restart" in result.content[0].text
    assert provider.calls == []
    with pytest.raises(ToolProfileBlocked):
        asyncio.run(run_gated_tool(registry, None, "hidden_write", {}))


def test_manifest_discovery_hides_modules_but_retains_required_workflows(tmp_path):
    modules = ModuleRegistry()
    modules.discover_and_load()
    registry = ProviderRegistry()
    provider = ModuleProvider(modules, WorkspaceMonitor([tmp_path]), registry)
    registry.register(provider)
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "daily"}))
    discovery = asyncio.run(provider.execute_tool("module_list_commands", {}))
    ids = {m["id"] for m in discovery["modules"]}
    assert {"revit_sparing", "revit_recipes", "revit_params", "revit_docs", "selection_tools", "revit", "revit_api"} <= ids
    assert "revit_mep" not in ids
    for identity in ids:
        assert not identity.startswith(("rhino", "speckle", "navisworks", "bcf_exchange", "clash_triage", "ifc", "revit_ifc"))


@pytest.mark.parametrize("command", ["revit_create_duct", "revit.create_duct", "revit_create_pipe"])
def test_jobs_cannot_wrap_hidden_native_mep_before_claim(tmp_path, command):
    revit = RevitProvider(workspace=WorkspaceMonitor([tmp_path]))
    jobs = RevitJobProvider(revit, JobManager())
    registry = registry_with(revit, jobs)
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "daily"}))
    gate = SimpleNamespace(claim_action=lambda *a: pytest.fail("hidden job claimed"))
    with pytest.raises(ToolProfileBlocked):
        gate_before(registry, gate, "revit_run_job", {"command": command})
    with pytest.raises(ToolProfileBlocked):
        jobs._resolve({"command": command})


@pytest.mark.parametrize("nested_job", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_existing_plan_hidden_action_is_not_claimed(tmp_path, monkeypatch, nested_job, mixed):
    workspace = WorkspaceMonitor([tmp_path])
    revit = RevitProvider(workspace=workspace)
    jobs = RevitJobProvider(revit, JobManager())
    registry = registry_with(revit, jobs)
    approval = ApprovalProvider(workspace, registry, approval_mode="required")
    registry.register(approval)
    target = "revit_run_job" if nested_job else "revit_create_pipe"
    args = {"command": "revit_create_pipe"} if nested_job else {}
    actions = ([{"tool": "revit_execute_python", "arguments": {"script": "pass", "mode": "write"}}]
               if mixed else [])
    actions.append({"tool": target, "arguments": args})
    plan = approval.gate.create_plan(actions, {})
    approval.gate.update_plan_state(plan["plan_id"], "approved", approver="test", via="cli", expected_hash=plan["plan_hash"])
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "daily"}))
    monkeypatch.setattr(approval.gate, "claim_action", lambda *a: pytest.fail("hidden plan action claimed"))
    with pytest.raises(ToolProfileBlocked, match="profile 'daily'"):
        asyncio.run(approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]}))
    saved = approval.gate.load_plan(plan["plan_id"])
    assert saved["state"] == "approved"
    assert "executed_at" not in saved
    assert approval.gate.load_proof(plan["plan_id"]) is None
    assert all(action["state"] == "pending" for action in saved["actions"])


def test_custom_jobs_cannot_wrap_hidden_python_provider(tmp_path):
    revit = RevitProvider(workspace=WorkspaceMonitor([tmp_path]))
    jobs = RevitJobProvider(revit, JobManager())
    registry = registry_with(revit, jobs)
    registry.freeze_tool_profile(ToolProfile(name="custom", exclude=("revit",)))
    gate = SimpleNamespace(claim_action=lambda *a: pytest.fail("hidden script job claimed"))
    with pytest.raises(ToolProfileBlocked):
        gate_before(registry, gate, "revit_run_job", {"script": "pass", "mode": "write"})


def test_daily_retains_native_audited_calls_and_write_approval(tmp_path):
    revit = RevitProvider(workspace=WorkspaceMonitor([tmp_path]))
    registry = registry_with(revit)
    registry.freeze_tool_profile(load_tool_profile({"MCP_REVIT_TOOL_PROFILE": "daily"}))
    for name in ("revit_get_context", "revit_execute_python", "revit_get_result"):
        assert registry.lookup_tool(name) is not None
    assert registry.lookup_tool("revit_execute_python").is_mutating
    claimed = []
    gate = SimpleNamespace(claim_action=lambda *a: claimed.append(a) or {"action_id": "test"})
    gate_before(registry, gate, "revit_execute_python", {"script": "pass", "mode": "write"})
    assert claimed


def test_panel_registry_is_unfiltered_even_when_env_requests_daily(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_TOOL_PROFILE", "daily")
    provider = FakeProvider("module", [tool("native_alias", "revit_mep")])
    registry = registry_with(provider)
    assert registry.lookup_tool("native_alias") is not None
    assert registry.is_tool_visible("native_alias")
