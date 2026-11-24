"""llms-full.txt and docs/error-catalogue.md are generated; they must not drift.

Fix a failure here by running the script it names and committing the result.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def llms_full():
    return _load("make_llms_full")


@pytest.fixture(scope="module")
def catalogue():
    return _load("make_error_catalogue")


def test_llms_full_is_current(llms_full) -> None:
    current = (ROOT / "llms-full.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == llms_full.build(), "llms-full.txt is stale. Run: python scripts/make_llms_full.py"


def test_llms_full_content_rules(llms_full) -> None:
    files, pointers = llms_full.file_list()
    assert files[:2] == ["llms.txt", "AGENTS.md"]
    assert len(files) == len(set(files))
    for rel in files:
        assert (ROOT / rel).is_file()
        assert not rel.startswith("docs/i18n/")
    assert "THIRD_PARTY_NOTICES.md" not in files
    assert "docs/tools-generated.md" not in files and "docs/tools-generated.md" in pointers
    text = (ROOT / "llms-full.txt").read_text(encoding="utf-8")
    assert text.count("\n=== FILE: ") == len(files)


def test_llms_txt_links_the_generated_docs() -> None:
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "/blob/main/llms-full.txt)" in text
    assert "/blob/main/docs/error-catalogue.md)" in text
    assert (ROOT / "llms-full.txt").is_file()


def test_troubleshooting_links_the_catalogue() -> None:
    assert "](error-catalogue.md)" in (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")


def test_error_catalogue_is_current(catalogue) -> None:
    current = (ROOT / "docs" / "error-catalogue.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == catalogue.build(), "docs/error-catalogue.md is stale. Run: python scripts/make_error_catalogue.py"


def test_every_code_in_source_has_an_entry_and_none_is_stale(catalogue) -> None:
    found = catalogue.collect()
    notes = catalogue.load_notes()
    assert not catalogue.problems(found, notes), "\n".join(catalogue.problems(found, notes))
    assert set(found) == set(notes)


def test_collector_finds_the_known_codes(catalogue) -> None:
    found = catalogue.collect()
    for key in (
        "mcp/approval_blocked", "mcp/human_only", "mcp/unknown_tool",
        "class/PolicyError", "class/ApprovalExpired", "class/ToolProfileBlocked", "class/CommandFailed",
        "kind/path_outside_workspace", "kind/approval_required", "kind/timeout_running",
    ):
        assert key in found, key


def test_catalogue_text_rules() -> None:
    text = (ROOT / "docs" / "error-catalogue.md").read_text(encoding="utf-8")
    assert not re.search(r"[^\x00-\x7f]", text), "non-ASCII (emoji or smart punctuation) in the catalogue"
    assert text.count("- When: ") == text.count("- What to do: ") == text.count("- Source: ")
