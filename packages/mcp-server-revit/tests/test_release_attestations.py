"""Release workflows attest build provenance for every published artifact, with job-scoped permissions."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
ATTEST_RE = re.compile(r"^actions/attest-build-provenance@[0-9a-f]{40}$")


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("workflow, subject", [
    ("release.yml", "dist/release/*"),  # .mcpb, add-in zips, installer, SBOM, checksums
    ("publish-pypi.yml", "packages/mcp-server-revit/dist/*"),  # wheel and sdist
])
def test_release_artifacts_are_attested_with_job_scoped_permissions(workflow, subject):
    data = _load(workflow)
    top = data.get("permissions") or {}
    assert "id-token" not in top and "attestations" not in top
    attesting = []
    for name, job in data["jobs"].items():
        for step in job.get("steps", []):
            uses = step.get("uses", "")
            if uses.startswith("actions/attest-build-provenance@"):
                assert ATTEST_RE.match(uses), f"{workflow}:{name} must pin the action by full commit SHA"
                assert step["with"]["subject-path"] == subject
                attesting.append(name)
    assert attesting, f"{workflow} has no build provenance step"
    for name in attesting:
        perms = data["jobs"][name]["permissions"]
        assert perms.get("id-token") == "write" and perms.get("attestations") == "write"


def test_publish_job_keeps_only_trusted_publishing_permission():
    perms = _load("publish-pypi.yml")["jobs"]["publish"]["permissions"]
    assert perms == {"id-token": "write"}


def test_both_workflows_pin_the_same_attest_action():
    pins = set()
    for name in ("release.yml", "publish-pypi.yml"):
        pins |= set(re.findall(r"actions/attest-build-provenance@([0-9a-f]{40})", (WORKFLOWS / name).read_text("utf-8")))
    assert len(pins) == 1
