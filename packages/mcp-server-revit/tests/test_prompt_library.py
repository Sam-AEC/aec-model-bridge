"""docs/prompts/*.md must name real tools and keep every write behind a plan.

Tool names are checked against the live registry, the same way
test_mcp_prompts_resources.py checks the MCP prompts.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from revit_mcp_server import mcp_prompts
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS
from revit_mcp_server.security.workspace import WorkspaceMonitor

ROOT = Path(__file__).resolve().parents[3]
PROMPTS = ROOT / "docs" / "prompts"
INDEX = PROMPTS / "README.md"
LIBRARY = sorted(p for p in PROMPTS.glob("*.md") if p.name != "README.md")
THEMED = [p for p in LIBRARY if re.search(r"^### [A-Z]+-\d+ ", p.read_text(encoding="utf-8"), re.MULTILINE)]

SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
BACKTICKED = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")
SECTION = re.compile(r"^### ([A-Z]+-\d+) .*?(?=^### |\Z)", re.MULTILINE | re.DOTALL)
TEXT_BLOCK = re.compile(r"```text\n(.*?)```", re.DOTALL)
# Writes that end in a plan; revit_execute_python is excluded because mode "read" needs no plan.
PLAN_TOOLS = {"plan_actions", "execute_plan"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.fixture(scope="module")
def registry_names(tmp_path_factory):
    registry, *_ = build_registry(WorkspaceMonitor([tmp_path_factory.mktemp("prompt_lib")]))
    tools = {t.name: t for _p, t in registry.get_tools_with_providers()}
    words = set()
    for tool in tools.values():
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
        for name, prop in (schema.get("properties") or {}).items():
            words.add(name)
            words.update(v for v in prop.get("enum") or [] if isinstance(v, str))
    words.update(mcp_prompts.prompt_names())  # the server's own MCP prompts
    mutating = {n for n, t in tools.items() if getattr(t, "is_mutating", False)}
    return set(tools), words, mutating


def sections(path: Path) -> dict[str, str]:
    return {m.group(1): m.group(0) for m in SECTION.finditer(read(path))}


def tools_line(body: str) -> list[str]:
    line = re.search(r"^- \*\*Tools:\*\* (.+)$", body, re.MULTILINE)
    assert line, "missing **Tools:** line"
    return BACKTICKED.findall(line.group(1))


def test_library_has_themed_files_and_enough_prompts():
    assert len(THEMED) >= 9
    assert sum(len(sections(p)) for p in THEMED) >= 40


@pytest.mark.parametrize("path", THEMED, ids=lambda p: p.name)
def test_each_prompt_has_the_required_fields(path, registry_names):
    _known, _words, mutating = registry_names
    found = sections(path)
    assert found, path.name
    for pid, body in found.items():
        for field in ("**When to use:**", "**Prompt:**", "**Expected result:**", "**Tested:**"):
            assert field in body, (path.name, pid, field)
        assert TEXT_BLOCK.search(body), (path.name, pid, "prompt text block")
        tested = re.search(r"\*\*Tested:\*\* (Mock: exercised|Untested)", body)
        assert tested, (path.name, pid, "Tested must start with 'Mock: exercised' or 'Untested'")
        tools = set(tools_line(body))
        assert tools, (path.name, pid)
        writes = tools & (PLAN_TOOLS | (mutating - {"revit_execute_python"}))
        if writes:
            assert "**Safety:**" in body, (path.name, pid, "write prompt needs a Safety note")
            assert "cannot approve" in TEXT_BLOCK.search(body).group(1), (path.name, pid)


@pytest.mark.parametrize("path", LIBRARY + [INDEX], ids=lambda p: p.name)
def test_every_tool_name_exists_in_the_registry(path, registry_names):
    known, words, _mutating = registry_names
    text = read(path)
    for pid, body in sections(path).items():
        names = set(tools_line(body))
        assert not names - known, (path.name, pid, sorted(names - known))
        assert not names & HUMAN_ONLY_TOOLS, (path.name, pid)
    # Every backticked identifier, and every identifier in a themed prompt's text, is a
    # registered tool or one of their argument names or enum values. Placeholders in {} are skipped.
    tokens = set(BACKTICKED.findall(text))
    if path in THEMED:
        for block in TEXT_BLOCK.findall(text):
            tokens |= set(SNAKE.findall(re.sub(r"\{[^}]*\}", "", block)))
    unknown = tokens - known - words
    assert not unknown, (path.name, sorted(unknown))
    assert "approve it yourself" not in text.lower()


def test_index_counts_match_the_files():
    rows = dict(re.findall(r"^\| \[([a-z0-9-]+\.md)\]\([a-z0-9-]+\.md\) \| (\d+) \|", read(INDEX), re.MULTILINE))
    assert set(rows) == {p.name for p in LIBRARY}
    for path in THEMED:
        assert int(rows[path.name]) == len(sections(path)), path.name


def test_prompt_library_is_linked():
    assert "docs/prompts/README.md" in read(ROOT / "README.md")
    assert "docs/prompts/README.md" in read(ROOT / "llms.txt")
