"""Contributor tooling stays in step with what it describes: the README coverage badge,
the dev container and the pre-commit hooks."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "packages" / "mcp-server-revit"


def test_readme_coverage_badge_matches_fail_under():
    floor = tomllib.loads((PKG / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "coverage"
    ]["report"]["fail_under"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    badges = re.findall(r"badge/coverage_floor-(\d+)%25", readme)
    assert badges == [str(floor)], (
        "the README coverage badge must state pyproject's fail_under"
    )
    head = readme.split("\n## ", 1)[0]
    assert "coverage_floor" in head, (
        "the badge belongs with the other badges at the top"
    )


def test_devcontainer_is_python_313_mock_mode_with_uv():
    data = json.loads(
        (ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
    )
    assert data["containerEnv"]["MCP_REVIT_MODE"] == "mock"
    assert "python:3.13" in data["image"]
    assert "uv sync --all-extras" in data["postCreateCommand"]
    assert "packages/mcp-server-revit" in data["postCreateCommand"]


def test_pre_commit_hooks_run_what_ci_runs():
    text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ruff check src tests" in text and "ruff check src tests" in ci
    assert (
        "python scripts/version.py check" in text
        and "python scripts/version.py check" in ci
    )
    assert (
        "tests/test_tool_count_claims.py" in text
        and (PKG / "tests" / "test_tool_count_claims.py").is_file()
    )
    # ruff format is reported, not enforced, in CI; a hook must not be stricter.
    enforced = "ruff format --check" in ci and "not enforced" not in ci
    assert ("ruff format" in text.split("repos:", 1)[1]) == enforced
