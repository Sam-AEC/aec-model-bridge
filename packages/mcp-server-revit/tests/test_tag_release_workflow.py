"""tag-release.yml tags the merge commit of a release PR with the RELEASE_TAG_TOKEN secret."""
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
    assert 'ls-remote --exit-code --tags "$remote" "refs/tags/${tag}"' in run
    skip = run.split("ls-remote", 1)[1].split("fi", 1)[0]
    assert "exit 0" in skip
    assert run.index("ls-remote") < run.index("tag -a") < run.index("git push")


def test_tag_is_pushed_with_the_secret_and_starts_release_by_tag_push():
    text = _text()
    run = _run_block()
    assert "TAG_TOKEN: ${{ secrets.RELEASE_TAG_TOKEN }}" in text
    assert "persist-credentials: false" in text
    assert 'git push "$remote" "refs/tags/${tag}"' in run
    assert "gh workflow run" not in run, "a token tag push already starts release.yml"
    release = RELEASE.read_text(encoding="utf-8").split("jobs:", 1)[0]
    assert re.search(r"push:\s+tags:", release)


def test_missing_secret_skips_without_error():
    run = _run_block()
    guard = run.split('if [ -z "${TAG_TOKEN}" ]; then', 1)[1].split("fi", 1)[0]
    assert "exit 0" in guard
    assert run.index("TAG_TOKEN") < run.index("git push")


def test_no_expression_interpolation_in_run_blocks():
    assert "${{" not in _run_block()


def test_permissions_are_minimal():
    text = _text()
    head, jobs = text.split("jobs:", 1)
    assert re.search(r"^permissions: \{\}$", head, re.MULTILINE)
    job_perms = jobs.split("permissions:", 1)[1].split("steps:", 1)[0]
    assert "contents: read" in job_perms
    assert len(re.findall(r"^\s+\w[\w-]*: (read|write)$", job_perms, re.MULTILINE)) == 1


def test_actions_are_pinned_by_sha_and_runner_is_hardened():
    uses = re.findall(r"^\s+uses: (\S+)", _text(), re.MULTILINE)
    assert uses and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses)
    assert any(u.startswith("step-security/harden-runner@") for u in uses)


def test_tag_ruleset_keeps_admin_only_bypass():
    # A personal repository cannot add the GitHub Actions integration as a bypass actor.
    bypass = json.loads(TAG_RULESET.read_text(encoding="utf-8"))["bypass_actors"]
    assert bypass == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
