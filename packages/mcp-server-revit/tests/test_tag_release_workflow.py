"""tag-release.yml tags the merge commit of a release PR and starts release.yml."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "tag-release.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
TAG_RULESET = ROOT / ".github" / "rulesets" / "protect-tags.json"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _run_block() -> str:
    return _text().split("run: |", 1)[1]


def test_trigger_is_closed_pull_request_into_main():
    text = _text()
    assert "pull_request:" in text and "types: [closed]" in text
    assert "branches: [main]" in text
    assert "push:" not in text.split("jobs:", 1)[0]


def test_job_runs_only_for_merged_release_heads_of_this_repo():
    cond = _text().split("if: >-", 1)[1].split("runs-on:", 1)[0]
    assert "github.event.pull_request.merged == true" in cond
    assert "head.repo.full_name == github.repository" in cond
    assert "head.ref == 'dev'" in cond
    assert "startsWith(github.event.pull_request.head.ref, 'release/')" in cond


def test_version_is_validated_and_tag_is_on_the_merge_commit():
    text = _text()
    run = _run_block()
    assert r"'^[0-9]+\.[0-9]+\.[0-9]+$'" in run
    assert "ref: ${{ github.event.pull_request.merge_commit_sha }}" in text
    assert 'tag -a "$tag" "$MERGE_SHA"' in run
    assert 'rev-parse HEAD)" != "$MERGE_SHA"' in run
    assert "set -euo pipefail" in run


def test_existing_tag_is_skipped_without_error():
    run = _run_block()
    assert 'ls-remote --exit-code --tags origin "refs/tags/${tag}"' in run
    skip = run.split("ls-remote", 1)[1].split("fi", 1)[0]
    assert "exit 0" in skip
    assert run.index("ls-remote") < run.index("tag -a") < run.index("git push")


def test_release_is_dispatched_explicitly_and_release_workflow_accepts_it():
    run = _run_block()
    assert 'gh workflow run release.yml --ref "$tag" -f tag="$tag"' in run
    release = RELEASE.read_text(encoding="utf-8").split("jobs:", 1)[0]
    assert "workflow_dispatch:" in release
    assert re.search(r"push:\s+tags:", release), "a manual tag push must still start the release"


def test_no_expression_interpolation_in_run_blocks():
    assert "${{" not in _run_block()


def test_permissions_are_minimal():
    text = _text()
    head, jobs = text.split("jobs:", 1)
    assert re.search(r"^permissions: \{\}$", head, re.MULTILINE)
    job_perms = jobs.split("permissions:", 1)[1].split("steps:", 1)[0]
    assert "contents: write" in job_perms and "actions: write" in job_perms
    assert len(re.findall(r"^\s+\w[\w-]*: (read|write)$", job_perms, re.MULTILINE)) == 2


def test_actions_are_pinned_by_sha_and_runner_is_hardened():
    uses = re.findall(r"^\s+uses: (\S+)", _text(), re.MULTILINE)
    assert uses and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses)
    assert any(u.startswith("step-security/harden-runner@") for u in uses)


def test_tag_ruleset_lets_github_actions_create_tags():
    bypass = json.loads(TAG_RULESET.read_text(encoding="utf-8"))["bypass_actors"]
    assert {"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"} in bypass
    assert {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"} in bypass
