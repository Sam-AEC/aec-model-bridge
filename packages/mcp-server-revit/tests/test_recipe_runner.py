"""Tests for Phase 15 — Recipe Runner module (AI orchestration)."""
import importlib.util
import pytest
from pathlib import Path

from revit_mcp_server.config import Config
from revit_mcp_server.providers import AECProvider, ApprovalProvider, ModuleProvider, ProviderRegistry, ProviderTool
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.security.workspace import WorkspaceMonitor


def _load_mod(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_rr = _load_mod("src/revit_mcp_server/modules/recipe_runner/module.py", "_rr_impl")
RecipeRunnerModule = _rr.RecipeRunnerModule
_render = _rr._render
_check_condition = _rr._check_condition


class MockWorkspace:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return MockWorkspace(tmp_path)


@pytest.fixture
def module():
    return RecipeRunnerModule()


class SnapshotProvider(AECProvider):
    def get_identity(self) -> str:
        return "snapshot"

    def get_capabilities(self):
        return [
            ProviderTool(
                name="snapshot_take",
                description="Mock snapshot",
                inputSchema={"type": "object", "properties": {}, "required": []},
            )
        ]

    async def check_health(self):
        return {"status": "ok"}

    async def shutdown(self):
        pass

    async def execute_tool(self, name, arguments):
        return {"snapshot_id": "", "taken_at": "20260101"}


class MutatingProvider(AECProvider):
    def get_identity(self) -> str:
        return "mutating"

    def get_capabilities(self):
        return [
            ProviderTool(
                name="fake_mutate",
                description="Mock mutating tool",
                inputSchema={"type": "object", "properties": {}, "required": []},
                is_mutating=True,
            )
        ]

    async def check_health(self):
        return {"status": "ok"}

    async def shutdown(self):
        pass

    async def execute_tool(self, name, arguments):
        return {"status": "mutated"}


def _module_provider(tmp_path: Path, registry: ProviderRegistry) -> ModuleProvider:
    cfg = Config(
        workspace_dir=tmp_path,
        allowed_directories=[tmp_path],
        audit_log=tmp_path / "audit.log",
        enable_user_modules=False,
    )
    module_registry = ModuleRegistry(config_obj=cfg)
    module_registry.discover_and_load()
    return ModuleProvider(
        module_registry=module_registry,
        workspace=WorkspaceMonitor([tmp_path]),
        tool_registry=registry,
    )


# --- Template engine tests ---

def test_render_simple_key():
    assert _render("{{name}}", {"name": "Antigravity"}) == "Antigravity"

def test_render_nested():
    assert _render("{{snap.snapshot_id}}", {"snap": {"snapshot_id": "abc123"}}) == "abc123"

def test_render_no_match():
    assert _render("{{missing}}", {}) == ""

def test_render_dict():
    rendered = _render({"snapshot_id": "{{snap_id}}"}, {"snap_id": "xyz"})
    assert rendered == {"snapshot_id": "xyz"}


# --- Condition evaluator ---

def test_condition_true_gte():
    assert _check_condition("{{prev.count}} >= 0", {"prev": {"count": 5}}) is True

def test_condition_false_lt():
    assert _check_condition("{{prev.count}} < 0", {"prev": {"count": 5}}) is False

def test_condition_eq():
    assert _check_condition("{{prev.status}} == ok", {"prev": {"status": "ok"}}) is True

def test_condition_none_is_true():
    assert _check_condition(None, {}) is True


# --- Recipe listing ---

def test_list_recipes_includes_builtins(module):
    result = module.list_recipes()
    assert result["count"] >= 3
    recipe_ids = {r["id"] for r in result["recipes"]}
    assert "nightly_health_check" in recipe_ids
    assert "snapshot_publish" in recipe_ids
    assert "export_clash_import" in recipe_ids


# --- Dry run ---

def test_dry_run_plans_steps(module, workspace):
    result = module.run_recipe(
        recipe_id="nightly_health_check",
        args={},
        dry_run=True,
        workspace=workspace,
    )
    assert result["dry_run"] is True
    assert result["steps_total"] == 3
    assert all(s.get("dry_run") is True for s in result["steps"])


# --- Run with mock executor ---

def test_run_with_mock_executor(module, workspace):
    call_log = []

    def mock_executor(tool_name: str, args: dict) -> dict:
        call_log.append(tool_name)
        if tool_name == "snapshot_take":
            return {"snapshot_id": "snap-001", "taken_at": "2026-01-01T00:00:00Z", "elements_count": 6}
        if tool_name == "qaqc_checker_run_check":
            return {"total_findings": 2, "rules_run": 13}
        if tool_name == "report_generator_export_excel":
            return {"status": "exported", "output_file": "/tmp/report.xlsx"}
        return {}

    result = module.run_recipe(
        recipe_id="nightly_health_check",
        args={},
        dry_run=False,
        workspace=workspace,
        tool_executor=mock_executor,
    )
    assert result["steps_run"] == 3
    assert "snapshot_take" in call_log
    assert "qaqc_checker_run_check" in call_log


# --- Run log persistence ---

def test_runs_are_logged(module, workspace):
    module.run_recipe(recipe_id="nightly_health_check", dry_run=True, workspace=workspace)
    runs = module.list_runs(workspace=workspace)
    assert runs["count"] == 1
    assert runs["runs"][0]["recipe_id"] == "nightly_health_check"
    assert runs["runs"][0]["status"] == "dry_run"

def test_get_run_status(module, workspace):
    result = module.run_recipe(recipe_id="nightly_health_check", dry_run=True, workspace=workspace)
    status = module.get_run_status(run_id=result["run_id"], workspace=workspace)
    assert status["run_id"] == result["run_id"]
    assert status["status"] == "dry_run"

def test_filter_runs_by_recipe_id(module, workspace):
    module.run_recipe(recipe_id="nightly_health_check", dry_run=True, workspace=workspace)
    module.run_recipe(recipe_id="snapshot_publish", dry_run=True, workspace=workspace)
    runs = module.list_runs(recipe_id="nightly_health_check", workspace=workspace)
    assert runs["count"] == 1

def test_nonexistent_recipe_raises(module, workspace):
    with pytest.raises(ValueError, match="not found"):
        module.run_recipe(recipe_id="does_not_exist", workspace=workspace)


@pytest.mark.anyio
async def test_provider_executes_recipe_steps(tmp_path):
    registry = ProviderRegistry()
    provider = _module_provider(tmp_path, registry)
    registry.register(provider)
    registry.register(SnapshotProvider())

    result = await provider.execute_tool("recipe_runner_run_recipe", {"recipe_id": "nightly_health_check"})

    assert result["status"] == "completed"
    assert [step["tool"] for step in result["steps"]] == [
        "snapshot_take",
        "qaqc_checker_run_check",
        "report_generator_export_excel",
    ]
    assert (tmp_path / "nightly_health_20260101.xlsx").exists()


@pytest.mark.anyio
async def test_provider_recipe_steps_respect_approval_gate(tmp_path):
    recipe = tmp_path / "mutating.yaml"
    recipe.write_text(
        """
id: mutating
name: Mutating
steps:
  - id: mutate
    tool: fake_mutate
    args: {}
""".strip(),
        encoding="utf-8",
    )

    registry = ProviderRegistry()
    workspace = WorkspaceMonitor([tmp_path])
    registry.register(ApprovalProvider(workspace=workspace, registry=registry, approval_mode="required"))
    provider = _module_provider(tmp_path, registry)
    registry.register(provider)
    registry.register(MutatingProvider())

    result = await provider.execute_tool("recipe_runner_run_recipe", {"recipe_id": "mutating.yaml"})

    assert result["status"] == "failed"
    assert "requires a valid 'plan_id'" in result["steps"][0]["error"]
