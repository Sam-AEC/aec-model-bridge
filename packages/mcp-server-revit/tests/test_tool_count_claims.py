"""Every tool count stated in the docs and listing files must match scripts/count_tools.py.

One tool is one entry in the server's tools/list in the default setup (see the
docstring of scripts/count_tools.py). The script is run in a child process so
the environment of other tests cannot change the number.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "count_tools.py"
ROW_RE = re.compile(r"^\| [^|]+ \| (\d+) \|", re.MULTILINE)
# "300+ tools" and "more than 300 tools" are floors: true if the count is at least
# that, and stale if the real count has moved on by more than this.
FLOOR_SLACK = 40


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.fixture(scope="module")
def counts() -> dict:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True, check=True, timeout=300
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def expected_table(counts: dict) -> list[int]:
    p = counts["by_provider"]
    named = [p["revit"], p["approval"], p["module"], p["rhino"], p["speckle"], p["navisworks"], p["ifc"]]
    return [*named, counts["tools"] - sum(named)]


def test_script_is_sane(counts: dict) -> None:
    assert counts["tools"] == sum(counts["by_provider"].values())
    assert counts["tools"] > 200
    assert counts["addin_commands"] > 100


def test_readme_headline_and_table(counts: dict) -> None:
    text = read(ROOT / "README.md")
    assert int(re.search(r"(\d+) tools are listed", text).group(1)) == counts["tools"]
    assert [int(n) for n in ROW_RE.findall(text)] == expected_table(counts)


def test_readme_first_screen_count(counts: dict) -> None:
    # The line under the headline repeats the total ("... · 307 tools · ..."); it must not drift.
    head = read(ROOT / "README.md").split("## ", 1)[0]
    stated = [int(n) for n in re.findall(r"(?<![\d.])(\d{2,4}) tools\b", head)]
    assert stated, "README first screen no longer states the tool count"
    assert set(stated) == {counts["tools"]}


def test_llms_txt(counts: dict) -> None:
    text = read(ROOT / "llms.txt")
    match = re.search(r"Tools: (\d+) in the default setup.*?Revit has (\d+) of them", text)
    assert match, "llms.txt no longer states the tool count in the expected form"
    assert (int(match.group(1)), int(match.group(2))) == (counts["tools"], counts["by_provider"]["revit"])


def test_token_budget_header(counts: dict) -> None:
    text = read(ROOT / "docs" / "mcp-token-budget.md")
    match = re.search(r"exposes \*\*(\d+)\*\* tools", text)
    assert match, "docs/mcp-token-budget.md no longer states the tool count in the expected form"
    assert int(match.group(1)) == counts["tools"]


def test_changelog_states_the_current_count(counts: dict) -> None:
    # The topmost count statement is the newest: "Tool count is now N" in Unreleased, or
    # a release entry's "one tool count (N, ...)". Released entries are never edited.
    text = read(ROOT / "CHANGELOG.md")
    match = re.search(r"Tool count is now (\d+)|one tool count \((\d+)", text)
    assert match, "CHANGELOG.md no longer states the tool count in a known form"
    assert int(match.group(1) or match.group(2)) == counts["tools"]


@pytest.mark.parametrize(
    "relpath", ["server.json", "packages/mcp-server-revit/manifest.json", "glama.json", "smithery.yaml"]
)
def test_listing_files_floor_claims(counts: dict, relpath: str) -> None:
    text = read(ROOT / relpath)
    floors = [int(n) for n in re.findall(r"(\d+)\+ tools", text) + re.findall(r"more than (\d+) tools", text)]
    exact = [int(n) for n in re.findall(r"(?<![\d.])(?<!than )(\d{2,3}) tools", text)]
    for n in floors:
        assert n <= counts["tools"] < n + FLOOR_SLACK, f"{relpath} says {n}+ tools, count is {counts['tools']}"
    for n in exact:
        assert n == counts["tools"], f"{relpath} says {n} tools, count is {counts['tools']}"


def test_server_json_and_manifest_agree() -> None:
    server = json.loads(read(ROOT / "server.json"))["description"]
    manifest = json.loads(read(ROOT / "packages" / "mcp-server-revit" / "manifest.json"))["description"]
    assert server == manifest


@pytest.mark.parametrize("path", sorted((ROOT / "docs" / "i18n").glob("README.*.md")), ids=lambda p: p.name)
def test_translations_state_the_same_counts(counts: dict, path: Path) -> None:
    text = read(path)
    assert [int(n) for n in ROW_RE.findall(text)] == expected_table(counts)
    assert re.search(rf"(?<!\d){counts['tools']}(?!\d)", text)


def test_no_two_providers_register_the_same_tool_name(tmp_path, monkeypatch) -> None:
    # A module tool that reuses a native tool's name is shadowed: the call goes to the native tool (seen live with
    # revit_apply_view_template).
    import collections

    monkeypatch.setenv("MCP_REVIT_MODE", "mock")
    monkeypatch.setenv("MCP_REVIT_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_REVIT_ALLOWED_DIRECTORIES", str(tmp_path))
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.workspace import WorkspaceMonitor

    registry = build_registry(WorkspaceMonitor([tmp_path]))[0]
    owners = collections.defaultdict(list)
    for provider in registry.get_all_providers():
        for tool in provider.get_capabilities():
            owners[tool.name].append(provider.get_identity())
    assert {k: v for k, v in owners.items() if len(v) > 1} == {}
