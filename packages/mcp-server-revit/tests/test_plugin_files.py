"""Structural checks for the Claude Code plugin and marketplace files.

The plugin schema is written from the Claude Code plugin docs and has NOT been
checked against the live validator (`claude plugin validate`). These tests only
catch drift inside this repository: bad JSON, missing keys, dangling paths and a
server command that no longer matches the one the rest of the repo uses.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_DIR = ROOT / "plugin"
PLUGIN_JSON = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MCP_JSON = PLUGIN_DIR / ".mcp.json"
SKILL = PLUGIN_DIR / "skills" / "revit-review" / "SKILL.md"
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_marketplace_has_required_keys_and_existing_sources():
    data = load(MARKETPLACE)
    assert KEBAB.match(data["name"])
    assert data["owner"]["name"]
    assert data["plugins"], "marketplace lists no plugins"
    for entry in data["plugins"]:
        assert KEBAB.match(entry["name"])
        source = entry["source"]
        assert isinstance(source, str) and source.startswith("./")
        target = (ROOT / source).resolve()
        assert target.is_dir(), f"marketplace source {source} does not exist"
        assert (target / ".claude-plugin" / "plugin.json").is_file()


def test_plugin_json_required_keys_and_name_matches_marketplace():
    plugin = load(PLUGIN_JSON)
    for key in ("name", "version", "description", "author", "license"):
        assert plugin.get(key), f"plugin.json is missing {key}"
    assert KEBAB.match(plugin["name"])
    listed = {p["name"]: p for p in load(MARKETPLACE)["plugins"]}
    assert plugin["name"] in listed
    assert listed[plugin["name"]]["version"] == plugin["version"]
    assert plugin["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_skill_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md needs YAML frontmatter"
    fields = dict(
        line.split(":", 1) for line in match.group(1).splitlines() if ":" in line
    )
    name = fields["name"].strip()
    assert KEBAB.match(name)
    assert name == SKILL.parent.name
    assert fields["description"].strip()
    # The safety rules the skill exists to teach.
    lowered = text.lower()
    for phrase in ("approve", "never say a change was made", "demo mode", "live mode"):
        assert phrase in lowered, f"SKILL.md no longer mentions: {phrase}"


def test_mcp_server_command_matches_rest_of_repo():
    servers = load(MCP_JSON)["mcpServers"]
    assert len(servers) == 1
    for name, server in servers.items():
        assert KEBAB.match(name)
        assert server["env"]["MCP_REVIT_MODE"] == "bridge"
        assert "MCP_REVIT_APPROVAL_MODE" not in server["env"], (
            "never relax approval here"
        )

    server = servers["aec-model-bridge"]

    # Same entry the one-click install links are built from.
    spec = importlib.util.spec_from_file_location(
        "make_install_links", ROOT / "scripts" / "make_install_links.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert server["command"] == module.SERVER["command"]
    assert server["args"] == module.SERVER["args"]

    # The console script it launches exists, and the module behind it is the one
    # manifest.json starts.
    pyproject = tomllib.loads(
        (ROOT / "packages" / "mcp-server-revit" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    script = pyproject["project"]["scripts"][server["args"][-1]]
    manifest = load(ROOT / "packages" / "mcp-server-revit" / "manifest.json")
    module_name = manifest["server"]["mcp_config"]["args"][-1]
    assert script.split(":")[0] == module_name == "revit_mcp_server.mcp_server"

    # server.json is the registry entry for the same package.
    registry = load(ROOT / "server.json")
    assert registry["repository"]["subfolder"] == "packages/mcp-server-revit"
    assert "packages/mcp-server-revit" in server["args"][1]
    assert registry["repository"]["url"] in server["args"][1]


def test_manifest_privacy_policy_points_at_existing_doc():
    manifest = load(ROOT / "packages" / "mcp-server-revit" / "manifest.json")
    urls = manifest["privacy_policies"]
    assert urls and all(u.startswith("https://") for u in urls)
    assert urls[0].endswith("/main/docs/privacy.md")
    assert (ROOT / "docs" / "privacy.md").is_file()
