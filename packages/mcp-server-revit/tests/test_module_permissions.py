from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from revit_mcp_server.config import Config
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.providers.module_provider import ModuleProvider
from revit_mcp_server.security.module_permissions import MODULE_PERMISSIONS
from revit_mcp_server.security.workspace import WorkspaceMonitor

PKG = Path(__file__).resolve().parents[1]
GUIDE = PKG.parent.parent / "docs" / "module-authoring.md"


def _manifest_permissions(manifest: dict) -> set[str]:
    names = set(manifest.get("permissions", []))
    for cmd in manifest.get("commands", []):
        names.update(cmd.get("permissions", []))
    return names


def test_builtin_manifests_and_guide_use_the_canonical_permissions():
    used: set[str] = set()
    for path in (PKG / "src" / "revit_mcp_server" / "modules").glob("*/module.json"):
        perms = _manifest_permissions(json.loads(path.read_text(encoding="utf-8")))
        assert perms <= set(MODULE_PERMISSIONS), (path.parent.name, perms - set(MODULE_PERMISSIONS))
        used |= perms
    assert {"model.read", "files.write"} <= used

    text = GUIDE.read_text(encoding="utf-8")
    section = text[text.index("## 3. Permissions"):text.index("### What is enforced")]
    listed = set(re.findall(r"^- `([a-z]+\.[a-z]+)`:", section, flags=re.M))
    assert listed == set(MODULE_PERMISSIONS)
    assert "by file path" in text


def _provider(tmp_path, mode="enforce", permissions=()):
    module_dir = tmp_path / "mods" / "writer"
    module_dir.mkdir(parents=True)
    (module_dir / "module.json").write_text(json.dumps({
        "id": "writer", "name": "Writer", "version": "1.0.0",
        "permissions": list(permissions),
        "commands": [{"id": "write_it", "title": "Write", "is_mutating": False}],
    }), encoding="utf-8")
    (module_dir / "module.py").write_text(
        "from pathlib import Path\n"
        "def write_it(arguments, workspace):\n"
        "    target = workspace.assert_writable(Path(arguments['path']))\n"
        "    target.write_text('x')\n"
        "    return {'status': 'success'}\n",
        encoding="utf-8",
    )
    cfg = Config(workspace_dir=tmp_path, allowed_directories=[tmp_path], audit_log=tmp_path / "audit.log",
                 enable_user_modules=False, module_permission_mode=mode)
    registry = ModuleRegistry(config_obj=cfg)
    registry._load_module_dir(module_dir, "test")
    return ModuleProvider(registry, WorkspaceMonitor([tmp_path]))


@pytest.mark.anyio
async def test_write_without_files_write_is_refused(tmp_path):
    provider = _provider(tmp_path, permissions=["model.read"])
    target = tmp_path / "out.txt"
    with pytest.raises(BridgeError, match="files.write"):
        await provider.execute_tool("writer_write_it", {"path": str(target)})
    assert not target.exists()


@pytest.mark.anyio
async def test_write_with_files_write_is_allowed(tmp_path):
    provider = _provider(tmp_path, permissions=["model.read", "files.write"])
    target = tmp_path / "out.txt"
    assert (await provider.execute_tool("writer_write_it", {"path": str(target)}))["status"] == "success"
    assert target.exists()


@pytest.mark.anyio
async def test_warn_mode_logs_and_allows(tmp_path, caplog):
    provider = _provider(tmp_path, mode="warn", permissions=["model.read"])
    target = tmp_path / "out.txt"
    with caplog.at_level(logging.WARNING):
        await provider.execute_tool("writer_write_it", {"path": str(target)})
    assert target.exists()
    assert "files.write" in caplog.text


def test_unknown_permission_logs_a_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        _provider(tmp_path, permissions=["workspace.write"])
    assert "unknown permission 'workspace.write'" in caplog.text
