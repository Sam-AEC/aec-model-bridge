"""Handlers declared with only ``**_`` must be callable with no arguments.

Regression: ``_run_callable`` saw one parameter (the ``**_``), built no kwargs and then
fell back to ``func(arguments)`` positionally, which raised TypeError for
``naming_checker_list_example_conventions`` and ``pyrevit_bridge_list_pyrevit_scripts``.
"""
import pytest

from revit_mcp_server.config import Config
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.providers.module_provider import ModuleProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor


def _provider(tmp_path):
    cfg = Config(workspace_dir=tmp_path, allowed_directories=[tmp_path],
                 audit_log=tmp_path / "audit.log", enable_user_modules=False)
    registry = ModuleRegistry(config_obj=cfg)
    registry.discover_and_load()
    return ModuleProvider(module_registry=registry, workspace=WorkspaceMonitor([tmp_path]))


@pytest.mark.anyio
async def test_run_callable_var_keyword_only_handler(tmp_path):
    provider = _provider(tmp_path)

    def only_kwargs(**_):
        return {"ok": True}

    assert await provider._run_callable(only_kwargs, {"x": 1}) == {"ok": True}


@pytest.mark.anyio
async def test_run_callable_legacy_positional_handler_still_works(tmp_path):
    provider = _provider(tmp_path)

    def legacy(args):
        return {"got": args}

    assert await provider._run_callable(legacy, {"x": 1}) == {"got": {"x": 1}}


@pytest.mark.anyio
async def test_naming_checker_list_example_conventions_no_args(tmp_path):
    provider = _provider(tmp_path)
    res = await provider.execute_tool("naming_checker_list_example_conventions", {})
    assert res


@pytest.mark.anyio
async def test_pyrevit_list_scripts_no_args(tmp_path):
    provider = _provider(tmp_path)
    res = await provider.execute_tool("pyrevit_bridge_list_pyrevit_scripts", {})
    assert res


@pytest.mark.anyio
async def test_run_callable_var_positional_only_handler_gets_the_arguments_dict(tmp_path):
    provider = _provider(tmp_path)

    def star_args(*args):
        return {"got": args}

    assert await provider._run_callable(star_args, {"x": 1}) == {"got": ({"x": 1},)}


@pytest.mark.anyio
async def test_run_callable_positional_only_and_named_arguments_shapes(tmp_path):
    provider = _provider(tmp_path)

    def pos_only(arguments, /):
        return {"got": arguments}

    def named(args):
        return {"got": args}

    assert await provider._run_callable(pos_only, {"x": 1}) == {"got": {"x": 1}}
    assert await provider._run_callable(named, {"x": 1}) == {"got": {"x": 1}}


@pytest.mark.anyio
async def test_run_callable_kwargs_only_handler_gets_no_positional(tmp_path):
    provider = _provider(tmp_path)

    def kw(**kwargs):
        return {"kw": kwargs}

    assert await provider._run_callable(kw, {"x": 1}) == {"kw": {}}
