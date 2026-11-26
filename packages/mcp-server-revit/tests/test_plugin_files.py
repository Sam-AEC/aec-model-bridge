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

import pytest

ROOT = Path(__file__).resolve().parents[3]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_DIR = ROOT / "packages" / "claude-plugin"
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


# ---- every skill in the plugin --------------------------------------------------------

SKILLS = sorted((PLUGIN_DIR / "skills").glob("*/SKILL.md"))
OPERATOR_SKILL = PLUGIN_DIR / "skills" / "aec-model-bridge" / "SKILL.md"
BACKTICKED = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")


def frontmatter(path: Path) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    assert match, f"{path} needs YAML frontmatter"
    return {k.strip(): v.strip() for k, v in (
        line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_every_skill_has_frontmatter_and_is_listed_by_the_marketplace(skill):
    fields = frontmatter(skill)
    assert fields["name"] == skill.parent.name and KEBAB.match(fields["name"])
    assert fields["description"] and len(fields["description"]) <= 1024
    listed = " ".join(p["description"] for p in load(MARKETPLACE)["plugins"])
    assert fields["name"] in listed, f"marketplace.json does not mention skill {fields['name']}"


def test_operator_skill_teaches_the_rules():
    lowered = OPERATOR_SKILL.read_text(encoding="utf-8").lower()
    for phrase in ("server.dev_mode", "plans_required`, when present", "never approve",
                   "one plan per change set", "docs/error-catalogue.md", "codex", "cursor"):
        assert phrase in lowered, f"aec-model-bridge SKILL.md no longer mentions: {phrase}"


def test_operator_skill_names_only_real_tools(tmp_path):
    from revit_mcp_server.config import APPROVAL_MODES
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor
    from revit_mcp_server.tool_metadata import enrich_tool

    registry, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    # Enriched schemas, as clients see them (they add response_options and plan_id).
    tools = {t.name: enrich_tool(p.get_identity(), t) for p, t in registry.get_tools_with_providers()}
    # Backticked snake_case words that are not tools must be a schema property or enum
    # value, an approval mode, or an error kind from the catalogue.
    words = set(APPROVAL_MODES)
    for tool in tools.values():
        for name, prop in (tool.inputSchema.get("properties") or {}).items():
            words.add(name)
            words.update(v for v in (prop.get("enum") or []) if isinstance(v, str))
    catalogue = (ROOT / "docs" / "error-catalogue.md").read_text(encoding="utf-8")
    words.update(re.findall(r"^### `([a-z_]+)`", catalogue, re.M))
    named = set(BACKTICKED.findall(OPERATOR_SKILL.read_text(encoding="utf-8")))
    unknown = sorted(n for n in named if n not in tools and n not in words)
    assert not unknown, f"SKILL.md names tools that do not exist: {unknown}"
    # The tools the skill is built around must be named, so a rename breaks this test.
    for name in ("revit_get_context", "search_tools", "context_report", "snapshot_take",
                 "snapshot_compute", "plan_actions", "execute_plan", "list_pending_plans"):
        assert name in named and name in tools, name
