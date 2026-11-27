"""The release-freeze workflow freezes dev for release PRs from dev or release/* in this repository."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "release-freeze.yml"
FILTER_RE = re.compile(r"^\s*filter='([^']+)'$", re.MULTILINE)


def _filter() -> str:
    match = FILTER_RE.search(WORKFLOW.read_text(encoding="utf-8"))
    assert match, "release-freeze.yml must define the jq filter on one `filter='...'` line"
    return match.group(1)


def _pr(number, head, owner):
    return {"number": number, "headRefName": head, "headRepositoryOwner": {"login": owner}}


def test_filter_text_covers_dev_release_heads_and_owner():
    text = _filter()
    assert '.headRefName == "dev"' in text
    assert 'startswith("release/")' in text
    assert ".headRepositoryOwner.login == $owner" in text


def test_workflow_lists_prs_into_main_and_passes_owner_through_env():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--base main" in text and "--head dev" not in text
    assert 'jq -r --arg owner "${OWNER}"' in text
    assert "OWNER: ${{ github.repository_owner }}" in text
    run = text.split("run: |", 1)[1]
    assert "${{" not in run


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not on PATH")
def test_filter_selects_expected_prs_with_jq():
    prs = [
        _pr(1, "dev", "me"),
        _pr(2, "release/1.6.3", "me"),
        _pr(3, "dev", "forker"),
        _pr(4, "release/1.6.3", "forker"),
        _pr(5, "feature/x", "me"),
        _pr(6, "releases/x", "me"),
    ]
    out = subprocess.run(
        ["jq", "-r", "--arg", "owner", "me", _filter()],
        input=json.dumps(prs), capture_output=True, text=True, check=True,
    ).stdout.split()
    assert out == ["1", "2"]


def test_lookup_fails_closed():
    run = WORKFLOW.read_text(encoding="utf-8").split("run: |", 1)[1]
    assert "set -o pipefail" in run
    assert "-ge 500" in run and "--limit 500" in run
