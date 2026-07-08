import pytest
from pathlib import Path
from revit_mcp_server.config import Config
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.providers.module_provider import ModuleProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.errors import BridgeError

def test_module_registry_discovery(tmp_path):
    cfg = Config(
        workspace_dir=tmp_path,
        allowed_directories=[tmp_path],
        audit_log=tmp_path / "audit.log",
        enable_user_modules=False
    )
    registry = ModuleRegistry(config_obj=cfg)
    registry.discover_and_load()
    
    # Assert Hello World is loaded
    hello = registry.get_module("hello_world")
    assert hello is not None
    assert hello.manifest.name == "Hello World Module"

@pytest.mark.anyio
async def test_module_provider_execution(tmp_path):
    cfg = Config(
        workspace_dir=tmp_path,
        allowed_directories=[tmp_path],
        audit_log=tmp_path / "audit.log",
        enable_user_modules=False
    )
    registry = ModuleRegistry(config_obj=cfg)
    registry.discover_and_load()
    
    workspace = WorkspaceMonitor([tmp_path])
    provider = ModuleProvider(module_registry=registry, workspace=workspace)
    
    # Check capabilities list
    caps = provider.get_capabilities()
    cap_names = [c.name for c in caps]
    assert "hello_world_say_hello" in cap_names
    assert "module_list_commands" in cap_names
    
    # 1. Execute success case
    res = await provider.execute_tool("hello_world_say_hello", {"name": "Antigravity"})
    assert res["status"] == "success"
    assert "Hello, Antigravity!" in res["message"]
    
    # 2. Execute default case (applies default input value)
    res_default = await provider.execute_tool("hello_world_say_hello", {})
    assert res_default["status"] == "success"
    assert "Hello, World!" in res_default["message"]
    
    # 3. Execute blocker case via validate hook
    with pytest.raises(BridgeError) as exc_info:
        await provider.execute_tool("hello_world_say_hello", {"name": "blocker"})
    assert "blocked execution" in str(exc_info.value)
    
    # 4. Schema validation failure
    with pytest.raises(BridgeError) as exc_info:
        await provider.execute_tool("hello_world_say_hello", {"name": 1234})  # integer, not string
    assert "validation failed" in str(exc_info.value).lower()
    
    # 5. List commands tool
    list_res = await provider.execute_tool("module_list_commands", {})
    assert "modules" in list_res
    assert len(list_res["modules"]) >= 1
    assert list_res["modules"][0]["id"] == "hello_world"
