"""Nightly live test (#295): runner logic with a fake panel client, and the workflow's safety rules.

No Revit, network or secret is used. What a real Revit does is UNVERIFIED and is checked only on
the self-hosted runner.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
SPEC = importlib.util.spec_from_file_location("live_nightly_run", ROOT / "scripts/revit/nightly/run.py")
assert SPEC and SPEC.loader
nightly = importlib.util.module_from_spec(SPEC)
sys.modules["live_nightly_run"] = nightly
SPEC.loader.exec_module(nightly)
harness = nightly.harness
GUID = "b3e63473-1641-4c71-9425-510915cddc65"
TITLE = "canonical-scratch-20261125-010000"


def options(*extra):
    return nightly.parser().parse_args(["--pid", "123", "--expected-document", TITLE, "--expected-guid", GUID,
                                        "--element-id", "42", *extra])


def context(mode="ask_first", dev=False, plans=True, title=TITLE):
    return {"ok": True, "addin_supports_context": True, "busy": False,
            "document": {"title": title, "guid": GUID, "path": "unsaved", "is_family": False},
            "addin": {"module_id": "module-1", "assembly_file_time_utc": "2026-11-25T01:00:00Z"},
            "queue": {"depth": 0, "running": None},
            "server": {"approval_mode": mode, "dev_mode": dev, "plans_required": plans}}


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.01
        return self.now


class FakeClient:
    """Keeps one parameter and the plan states the real gate would enforce."""

    def __init__(self, ctx=None, ignore_gate=False, write_sticks=True, revert_fails=False, diff=None):
        self.ctx = ctx or context()
        self.value, self.original = "orig", "orig"
        self.plans, self.calls, self.snapshots = {}, [], 0
        self.ignore_gate, self.write_sticks, self.revert_fails = ignore_gate, write_sticks, revert_fails
        self.diff_result = diff

    def call(self, tool, args):
        self.calls.append(tool)
        if tool == "revit_get_context":
            return self.ctx
        if tool == "revit_execute_python":
            return {"success": True, "mode": "read", "model_changes_in_read_mode": 0,
                    "output": json.dumps({"identity": [TITLE, GUID], "elements": 10, "warnings": 2,
                                          "modifiable": False, "stdlib": [1, 2], "marker": ""})}
        if tool == "snapshot_take":
            self.snapshots += 1
            return {"status": "ok", "snapshot_id": f"snap-{self.snapshots}", "truncated": False,
                    "value_at_capture": self.value}
        if tool == "snapshot_diff":
            if self.diff_result is not None:
                return self.diff_result
            same = args["snapshot_b_id"] == "snap-3"
            return {"added_count": 0, "deleted_count": 0, "modified_count": 0 if same else 1}
        if tool == "revit_get_parameter_value":
            return {"value": self.value}
        if tool == "plan_actions":
            return self._draft(args["actions"])
        if tool == "plan_revert":
            if self.revert_fails:
                raise harness.AcceptanceError("Cannot revert: no before value was recorded.")
            return self._draft([{"tool": "revit_set_parameter_value",
                                 "arguments": {"element_id": "42", "parameter_name": "Comments", "value": self.original}}])
        if tool == "approve_plan":
            plan = self.plans[args["plan_id"]]
            assert args["expected_hash"] == plan["plan_hash"], "approval must be bound to the plan hash"
            plan["state"] = "approved"
            return plan
        if tool == "execute_plan":
            plan = self.plans[args["plan_id"]]
            if plan["state"] != "approved" and not self.ignore_gate:
                raise harness.AcceptanceError("Plan is not approved. Execution blocked.")
            if self.write_sticks or plan["actions"][0]["arguments"]["value"] == self.original:
                self.value = plan["actions"][0]["arguments"]["value"]
            plan["state"] = "executed"
            return {"plan_id": args["plan_id"], "state": "executed", "ok": True}
        raise AssertionError(f"unexpected tool {tool}")

    def _draft(self, actions):
        plan_id = f"plan-{len(self.plans) + 1}"
        plan = {"plan_id": plan_id, "plan_hash": "h" * 8 + str(len(self.plans)), "state": "pending", "actions": actions}
        self.plans[plan_id] = plan
        return plan


def run(client, *extra):
    return nightly.run_checks(client, options(*extra), clock=FakeClock())


def test_default_is_offline_and_reads_no_secret(monkeypatch, capsys):
    monkeypatch.setattr(harness, "read_token", lambda: pytest.fail("a plan must not read the token"))
    code = nightly.main(["--pid", "1", "--expected-document", TITLE, "--expected-guid", GUID, "--element-id", "42"])
    assert code == 0 and json.loads(capsys.readouterr().out)["status"] == "NOT_RUN"


def test_happy_path_writes_once_reverts_and_compares():
    client = FakeClient()
    report = run(client, "--self-approve")
    assert report["status"] == "PASS", report["checks"]
    assert client.value == "orig"
    assert client.calls.count("plan_actions") == 1 and client.calls.count("plan_revert") == 1
    assert client.calls.count("approve_plan") == 2
    for name in ("approved_write", "diff_write", "revert_write", "diff_revert", "read_counts_after"):
        assert report["checks"][name]["status"] == "PASS"
    assert all(isinstance(c["ms"], float) for c in report["checks"].values())
    assert report["total_ms"] > 0


def test_without_self_approve_nothing_is_drafted_or_written():
    client = FakeClient()
    report = run(client)
    assert report["status"] == "NOT_RUN"
    assert report["checks"]["approved_write"]["status"] == "NOT_RUN"
    assert not {"plan_actions", "approve_plan", "execute_plan"} & set(client.calls)


@pytest.mark.parametrize("ctx", [context(mode="auto"), context(mode="look_only"), context(dev=True),
                                 context(plans=False), context(title="Some project")])
def test_bad_preflight_stops_before_any_write(ctx):
    client = FakeClient(ctx=ctx)
    report = run(client, "--self-approve")
    assert report["status"] == "FAIL" and report["checks"]["preflight"]["status"] == "FAIL"
    assert not {"plan_actions", "approve_plan", "execute_plan", "snapshot_take"} & set(client.calls)


def test_production_document_is_refused_even_if_title_matches():
    ctx = context(title="Production project")
    ctx["document"]["path"] = r"C:\work\Production scratch.rvt"
    report = nightly.run_checks(FakeClient(ctx=ctx),
                                nightly.parser().parse_args(["--pid", "1", "--expected-document", "Production project",
                                                             "--expected-guid", GUID, "--element-id", "42",
                                                             "--self-approve"]), clock=FakeClock())
    assert report["checks"]["preflight"]["status"] == "FAIL"


def test_gate_that_runs_an_unapproved_plan_fails_the_run():
    report = run(FakeClient(ignore_gate=True), "--self-approve")
    assert report["status"] == "FAIL"
    assert "not approved" in report["checks"]["approved_write"]["detail"]


def test_failed_revert_is_reported_and_scratch_copy_flagged():
    client = FakeClient(revert_fails=True)
    report = run(client, "--self-approve")
    assert report["status"] == "FAIL"
    assert report["checks"]["revert_write"]["status"] == "FAIL"
    assert report["checks"]["cleanup_revert"]["status"] == "FAIL"
    assert "discard the scratch copy" in report["note"]


def test_failed_verification_after_write_still_tries_the_revert():
    client = FakeClient(diff={"added_count": 0, "deleted_count": 0, "modified_count": 3})
    report = run(client, "--self-approve")
    assert report["status"] == "FAIL"
    assert report["checks"]["diff_write"]["status"] == "FAIL"
    assert report["checks"]["cleanup_revert"]["status"] == "PASS"
    assert client.value == "orig"


def test_write_that_does_not_stick_fails():
    report = run(FakeClient(write_sticks=False), "--self-approve")
    assert report["checks"]["read_parameter_after_write"]["status"] == "FAIL"


def test_truncated_snapshot_fails_instead_of_comparing_partial_data():
    class Truncated(FakeClient):
        def call(self, tool, args):
            result = super().call(tool, args)
            return {**result, "truncated": True} if tool == "snapshot_take" else result

    report = run(Truncated(), "--self-approve")
    assert report["checks"]["snapshot_before"]["status"] == "FAIL"


def test_benchmark_merge_passes_fails_and_tolerates_missing(tmp_path):
    good = tmp_path / "bench.json"
    good.write_text(json.dumps({"client": {"revit.health": {"errors": 0, "p50_ms": 3}}, "burst": {"errors": 0}}),
                    encoding="utf-8-sig")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"client": {"revit.health": {"errors": 2}}, "burst": {"errors": 1}}))
    for path, status in ((good, "PASS"), (bad, "FAIL"), (tmp_path / "none.json", "FAIL"), (None, "NOT_RUN")):
        report = {"checks": {}}
        nightly.merge_bench(report, str(path) if path else None)
        assert report["checks"]["benchmark"]["status"] == status
    assert nightly.finish({"checks": {"a": {"status": "PASS"}, "benchmark": {"status": "NOT_RUN"}}})["status"] == "NOT_RUN"
    assert nightly.finish({"checks": {}})["status"] == "FAIL"


def test_evidence_is_written_inside_artifacts_only(tmp_path):
    report = run(FakeClient(), "--self-approve")
    with pytest.raises(harness.AcceptanceError):
        harness.write_evidence(report, tmp_path)


# Workflow safety.

@pytest.fixture(scope="module")
def workflow():
    text = (WORKFLOWS / "live-nightly.yml").read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def test_runs_only_on_schedule_or_dispatch(workflow):
    _text, data = workflow
    triggers = data.get(True, data.get("on"))  # YAML reads a bare `on` as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}


def test_runs_only_on_the_labelled_self_hosted_runner(workflow):
    _text, data = workflow
    assert set(data["jobs"]) == {"live"}
    job = data["jobs"]["live"]
    assert job["runs-on"] == ["self-hosted", "windows", "revit-live"]
    assert "github.repository ==" in job["if"] and "refs/heads/dev" in job["if"]
    assert "revit-live" in (ROOT / ".github" / "actionlint.yaml").read_text(encoding="utf-8")


def test_workflow_is_read_only_secret_free_and_pinned(workflow):
    text, data = workflow
    assert data["permissions"] == {"contents": "read"}
    assert data["jobs"]["live"]["permissions"] == {"contents": "read"}
    assert not re.search(r"\$\{\{\s*secrets\.", text) and ": write" not in text
    assert not re.search(r"\$\{\{\s*(github\.event|inputs)\.", text)
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{ref} is not pinned by full commit SHA"
        assert ref in ci, f"{ref} must use the same pin as ci.yml"
    checkout = [s for s in data["jobs"]["live"]["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout and checkout[0]["with"]["persist-credentials"] is False


def test_variables_reach_scripts_only_through_env(workflow):
    _text, data = workflow
    for step in data["jobs"]["live"]["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")


def test_report_is_uploaded_even_after_a_failure_and_cleanup_always_runs(workflow):
    _text, data = workflow
    steps = {s["name"]: s for s in data["jobs"]["live"]["steps"]}
    assert steps["Upload report"]["if"] == "always()"
    assert steps["Close Revit and delete the scratch copy"]["if"] == "always()"
    assert data["concurrency"]["cancel-in-progress"] is False
