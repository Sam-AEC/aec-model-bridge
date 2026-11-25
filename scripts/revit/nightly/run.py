"""Nightly live test on a scratch model (#295). One approved write, its revert and a snapshot comparison.

Runs on the self-hosted runner only (see README.md in this folder). The default is an offline
plan that makes no call and reads no secret. ``--run`` makes live calls through the authenticated
panel hub, pinned to one Revit process, and also needs ``--self-approve``: the runner approves its
own plan through the panel route, which tests the gate and nothing else. Both approvals are
bound to the plan hash. The target must be a scratch copy of the canonical model; the harness
identity check refuses any other document.

Not covered here: opening the scratch copy (``prepare-scratch.ps1``) and the add-in benchmark
(``scripts/bench-addin.ps1``, merged in through ``--bench-json``).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location("live_acceptance_harness", ROOT / "scripts/revit/acceptance/run.py")
assert _SPEC and _SPEC.loader
harness = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("live_acceptance_harness", harness)
_SPEC.loader.exec_module(harness)

AcceptanceError = harness.AcceptanceError
ARTIFACTS = ROOT / "artifacts" / "revit-nightly"
DEFAULT_PARAMETER = "Comments"
STATUSES = ("PASS", "FAIL", "SKIPPED", "NOT_RUN")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pid", type=int, required=True, help="Process id of the one Revit that holds the scratch copy.")
    p.add_argument("--expected-document", required=True, help="Exact title of the scratch copy.")
    p.add_argument("--expected-guid", required=True, help="CreationGUID of the canonical model (copies keep it).")
    p.add_argument("--element-id", required=True, help="Element with an editable text parameter in the canonical model.")
    p.add_argument("--parameter", default=DEFAULT_PARAMETER, help="Text parameter to write (default Comments).")
    p.add_argument("--hub", default="http://127.0.0.1:8787")
    p.add_argument("--bench-json", help="Report written by scripts/bench-addin.ps1; its timings are merged.")
    p.add_argument("--output-dir", default=str(ARTIFACTS), help="Must be inside the ignored artifacts folder.")
    p.add_argument("--run", action="store_true", help="Make live calls; otherwise emit only a plan.")
    p.add_argument("--self-approve", action="store_true",
                   help="Approve the test plans through the panel route. Without it the write steps are NOT_RUN.")
    p.add_argument("--snapshot-categories", nargs="*", default=None,
                   help="Limit the snapshots to these categories (default: the server's own limits).")
    return p


def harness_options(options: argparse.Namespace) -> argparse.Namespace:
    # Nightly runs are always on a scratch copy: the existing-document exemption is never offered.
    return argparse.Namespace(expected_document=options.expected_document, expected_guid=options.expected_guid,
                              allow_existing_test_document=False)


class Report:
    def __init__(self, options: argparse.Namespace, clock: Callable[[], float]):
        self.clock = clock
        self.data: dict[str, Any] = {
            "schema": "amb.nightly_live/1",
            "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
            "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "FAIL",
            "document": options.expected_document,
            "pid": options.pid,
            "note": "Written by a live run on the self-hosted runner. Not observed in CI.",
            "checks": {},
        }
        self.start = clock()

    def step(self, name: str, fn: Callable[[], Any], summary: Callable[[Any], Any] | None = None) -> Any:
        """Run one step, record its time and a short detail. Returns the value, or raises after recording."""
        began = self.clock()
        try:
            value = fn()
        except AcceptanceError as exc:
            self.data["checks"][name] = {"status": "FAIL", "ms": self._ms(began), "detail": str(exc)}
            raise
        detail = summary(value) if summary else value
        self.data["checks"][name] = {"status": "PASS", "ms": self._ms(began), "detail": detail}
        return value

    def mark(self, name: str, status: str, detail: str) -> None:
        assert status in STATUSES
        self.data["checks"].setdefault(name, {"status": status, "ms": 0, "detail": detail})

    def _ms(self, began: float) -> float:
        return round((self.clock() - began) * 1000, 1)

    def finish(self) -> dict[str, Any]:
        self.data["total_ms"] = self._ms(self.start)
        return finish(self.data)


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def counts(client: Any, options: argparse.Namespace) -> dict[str, Any]:
    output = harness.decode_read(harness.read_call(client, harness_options(options)), harness_options(options))
    return {"elements": output["elements"], "warnings": output["warnings"]}


def parameter_value(client: Any, options: argparse.Namespace) -> Any:
    result = client.call("revit_get_parameter_value", {"element_id": options.element_id, "parameter_name": options.parameter})
    need("value" in result, "Parameter read returned no value.")
    return result["value"]


def take_snapshot(client: Any, options: argparse.Namespace) -> str:
    args: dict[str, Any] = {}
    if options.snapshot_categories:
        args["categories"] = list(options.snapshot_categories)
    result = client.call("snapshot_take", args)
    need(isinstance(result.get("snapshot_id"), str) and result["snapshot_id"], "Snapshot returned no id.")
    need(not result.get("truncated"), "Snapshot was truncated; use --snapshot-categories to scope it.")
    return result["snapshot_id"]


def diff(client: Any, first: str, second: str) -> dict[str, int]:
    result = client.call("snapshot_diff", {"snapshot_a_id": first, "snapshot_b_id": second})
    return {k: result.get(k) for k in ("added_count", "deleted_count", "modified_count")}


def approve_and_execute(client: Any, plan: dict[str, Any], started: Callable[[], None] | None = None) -> dict[str, Any]:
    plan_id, plan_hash = plan.get("plan_id"), plan.get("plan_hash")
    need(isinstance(plan_id, str) and isinstance(plan_hash, str) and plan.get("state") == "pending",
         "Draft is not a pending plan with an id and a hash (is Dev mode on?).")
    # The gate must refuse an unapproved plan; a pass here would be a hole in the gate.
    try:
        client.call("execute_plan", {"plan_id": plan_id})
    except AcceptanceError:
        pass
    else:
        raise AcceptanceError("execute_plan ran a plan that was not approved.")
    client.call("approve_plan", {"plan_id": plan_id, "expected_hash": plan_hash})
    if started:
        started()  # from here on the model may have changed, even if the call below fails
    result = client.call("execute_plan", {"plan_id": plan_id})
    need(result.get("ok") is True and result.get("state") == "executed", "Plan did not finish as executed.")
    return result


def run_checks(client: Any, options: argparse.Namespace, *, clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    report = Report(options, clock)
    marker = "nightly-" + uuid.uuid4().hex[:10]
    state: dict[str, Any] = {"written": False, "reverted": False}
    try:
        _flow(client, options, report, marker, state)
    except AcceptanceError:
        pass  # recorded by report.step
    finally:
        if state["written"] and not state["reverted"]:
            _cleanup(client, options, report, state)
    data = report.finish()
    if state["written"] and not state["reverted"]:
        data["note"] += " The write was not reverted: discard the scratch copy."
    return data


def _flow(client: Any, options: argparse.Namespace, report: Report, marker: str, state: dict[str, Any]) -> None:
    def preflight() -> dict[str, Any]:
        context = client.call("revit_get_context", {})
        document = harness.identity(context, harness_options(options))
        server = context.get("server") or {}
        need(server.get("approval_mode") == "ask_first" and not server.get("dev_mode") and server.get("plans_required") is True,
             "Approval mode must be Ask me first with Dev off.")
        stamp = context["addin"]
        return {"title": document.get("title"), "module_id": stamp["module_id"], "assembly_file_time_utc": stamp["assembly_file_time_utc"]}

    report.step("preflight", preflight)
    before_counts = report.step("read_counts_before", lambda: counts(client, options))
    snap_a = report.step("snapshot_before", lambda: take_snapshot(client, options))
    original = report.step("read_parameter_before", lambda: parameter_value(client, options))
    if not options.self_approve:
        report.mark("approved_write", "NOT_RUN", "--self-approve was not given.")
        return
    write_action = {"tool": "revit_set_parameter_value", "arguments": {
        "element_id": options.element_id, "parameter_name": options.parameter, "value": marker}}
    plan = report.step("draft_write_plan", lambda: client.call("plan_actions", {"snapshot_id": snap_a, "actions": [write_action]}),
                       lambda p: {"plan_id": p.get("plan_id"), "plan_hash": p.get("plan_hash")})
    state["write_plan"] = plan.get("plan_id")

    def write() -> dict[str, Any]:
        result = approve_and_execute(client, plan, lambda: state.update(written=True))
        return {"plan_id": plan.get("plan_id"), "state": result.get("state")}

    report.step("approved_write", write)
    report.step("read_parameter_after_write", lambda: need(parameter_value(client, options) == marker,
                                                          "The parameter does not hold the written value.") or "ok")
    snap_b = report.step("snapshot_after_write", lambda: take_snapshot(client, options))
    report.step("diff_write", lambda: _expect_diff(diff(client, snap_a, snap_b), added=0, deleted=0, modified=1))
    _revert(client, options, report, state, original)
    snap_c = report.step("snapshot_after_revert", lambda: take_snapshot(client, options))
    report.step("diff_revert", lambda: _expect_diff(diff(client, snap_a, snap_c), added=0, deleted=0, modified=0))
    report.step("read_counts_after", lambda: _same_counts(before_counts, counts(client, options)))


def _revert(client: Any, options: argparse.Namespace, report: Report, state: dict[str, Any], original: Any) -> None:
    def revert() -> dict[str, Any]:
        draft = client.call("plan_revert", {"plan_id": state["write_plan"]})
        result = approve_and_execute(client, draft)
        state["reverted"] = True
        return {"plan_id": draft.get("plan_id"), "state": result.get("state")}

    report.step("revert_write", revert)
    report.step("read_parameter_after_revert", lambda: need(parameter_value(client, options) == original,
                                                           "The parameter does not hold its original value.") or "ok")


def _cleanup(client: Any, options: argparse.Namespace, report: Report, state: dict[str, Any]) -> None:
    """A step failed after the write. Try the revert once; the report says what happened."""
    name = "cleanup_revert"
    began = report.clock()
    try:
        draft = client.call("plan_revert", {"plan_id": state["write_plan"]})
        approve_and_execute(client, draft)
        state["reverted"] = True
        report.data["checks"][name] = {"status": "PASS", "ms": report._ms(began), "detail": "Reverted after an earlier failure."}
    except AcceptanceError as exc:
        report.data["checks"][name] = {"status": "FAIL", "ms": report._ms(began), "detail": str(exc)}


def _expect_diff(found: dict[str, int], *, added: int, deleted: int, modified: int) -> dict[str, int]:
    wanted = {"added_count": added, "deleted_count": deleted, "modified_count": modified}
    need(found == wanted, f"Snapshot comparison found {found}, expected {wanted}.")
    return found


def _same_counts(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    need(before == after, f"Element or warning counts changed: {before} then {after}.")
    return after


def merge_bench(report: dict[str, Any], path: str | None) -> None:
    """Add the add-in benchmark's timings. A missing or failing benchmark fails the run."""
    if not path:
        report["checks"]["benchmark"] = {"status": "NOT_RUN", "ms": 0, "detail": "No --bench-json given."}
        return
    try:
        bench = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        client_rows = bench["client"]
        errors = sum(int(row.get("errors", 0)) for row in client_rows.values()) + int((bench.get("burst") or {}).get("errors", 0))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        report["checks"]["benchmark"] = {"status": "FAIL", "ms": 0, "detail": "The benchmark report is missing or unreadable."}
        return
    report["benchmark"] = {"client": client_rows, "burst": bench.get("burst"), "addin_timings": bench.get("addin_timings"),
                           "host_version": bench.get("host_version")}
    report["checks"]["benchmark"] = {"status": "PASS" if errors == 0 else "FAIL", "ms": 0,
                                     "detail": f"{errors} failed call(s) in the benchmark."}


def finish(report: dict[str, Any]) -> dict[str, Any]:
    """Overall status: any FAIL (or no check at all) fails, then any NOT_RUN, else PASS."""
    statuses = [c["status"] for c in report["checks"].values()]
    if "FAIL" in statuses or not statuses:
        report["status"] = "FAIL"
    elif "NOT_RUN" in statuses:
        report["status"] = "NOT_RUN"
    else:
        report["status"] = "PASS"
    return report


def main(argv: list[str] | None = None) -> int:
    options = parser().parse_args(argv)
    if not options.run:
        print(json.dumps({"status": "NOT_RUN", "plan": "Would run preflight, benchmark merge, snapshot, one approved "
                          "write, its revert and a snapshot comparison. Add --run for live calls."}, indent=2))
        return 0
    token = harness.read_token()
    client = harness.PanelClient(options.hub, options.pid, token)
    report = run_checks(client, options)
    merge_bench(report, options.bench_json)
    finish(report)
    path = harness.write_evidence(report, Path(options.output_dir))
    print(json.dumps({"status": report["status"], "report": str(path)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
