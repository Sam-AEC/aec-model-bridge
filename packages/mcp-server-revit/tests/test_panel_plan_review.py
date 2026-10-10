"""The panel shows the plan's hashed review block, and fails closed when it cannot.

Covers the hub payload (``review_view`` on the panel's list_pending_plans route only), the
redaction interaction (output redaction must never change what a person approves without
the panel refusing Approve), the real MCP path, static guards on panel/app.js and the
fail-closed rule for real hub output in a node stub-DOM harness. The stub DOM does not build
the review; drawing it is tested in the headless-Chromium cases of tests/panel_web/app_driver.js.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import threading
from pathlib import Path

import pytest

from revit_mcp_server import mcp_server
from revit_mcp_server.panel_server import build_server
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security import proof
from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS, plan_hash
from revit_mcp_server.security.audit import redact_data
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_panel_a11y import HARNESS, _run  # noqa: F401  (stub-DOM harness)
from test_panel_server import _post

APP_JS = (Path(__file__).resolve().parents[3] / "panel" / "app.js").read_text(encoding="utf-8")
SET = "revit_set_parameter_value"
REVERTED = "plan_0123456789ab"

REVIEW = {
    "summary": "Raise fire rating to 60",
    "reasoning": "Corridor walls need 60 min.",
    "citations": [{"rule_id": "FIRE-001", "clause": "B3.2", "source": "Approved Document B"}],
    "assumptions": ["Walls are load bearing"],
    "excluded": [{"element_id": 9, "reason": "linked model"}],
    "warnings": ["Check with the fire engineer"],
    "conflicts": [{"element_id": 1, "parameter": "FireRating", "expected_current": "60",
                   "actual_current": "90", "revert_to": "30"}],
}


@pytest.fixture
def hub(tmp_path):
    server = build_server(port=0, workspace=WorkspaceMonitor([tmp_path]))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], tmp_path
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _draft(port, review=None, actions=None):
    args = {"actions": actions or [{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "A"}}]}
    if review is not None:
        args["review"] = review
    status, body = _post(port, "/execute", {"tool": "plan_actions", "arguments": args})
    assert status == 200, body
    return body["result"]


def _list(port):
    status, body = _post(port, "/execute", {"tool": "list_pending_plans", "arguments": {}})
    assert status == 200
    return body["result"]


def _pending(port):
    return {p["plan_id"]: p for p in _list(port)["plans"]}


def _plan_file(tmp_path, plan_id):
    matches = list(tmp_path.rglob(f"plans/{plan_id}.json"))
    assert len(matches) == 1
    return matches[0]


def _edit(tmp, plan_id, mutate, rehash=True):
    path = _plan_file(tmp, plan_id)
    stored = json.loads(path.read_text("utf-8"))
    mutate(stored)
    if rehash:
        stored["plan_hash"] = plan_hash(stored)
    path.write_text(json.dumps(stored), "utf-8")


def _approve(port, plan_id, plan_hash_):
    return _post(port, "/execute", {"tool": "approve_plan",
                                    "arguments": {"plan_id": plan_id, "expected_hash": plan_hash_}})


# ------------------------------------------------------------------ hub payload


def test_panel_payload_carries_review_version_and_reverts_id(hub):
    port, tmp = hub
    plan = _draft(port, REVIEW)
    _edit(tmp, plan["plan_id"], lambda p: p.update(reverts_plan_id=REVERTED))
    got = _pending(port)[plan["plan_id"]]
    view = got["review_view"]
    assert view["status"] == "ok" and view["hash_version"] == 2
    assert view["review"] == proof.normalize_review(REVIEW)
    assert view["reverts_plan_id"] == REVERTED
    assert "review" not in got, "the panel must read only the validated copy"


def test_plan_without_review_is_version_one_none(hub):
    port, _ = hub
    plan = _draft(port)
    view = _pending(port)[plan["plan_id"]]["review_view"]
    assert view["status"] == "none" and view["hash_version"] == 1 and view["review"] is None


def _tamper(mutate, rehash=False):
    def go(port, tmp):
        plan = _draft(port, REVIEW)
        _edit(tmp, plan["plan_id"], mutate, rehash=rehash)
        return plan["plan_id"]
    return go


def _drop_review(p):
    del p["review"]


def _extra_key(p):
    p["review"]["injected"] = "x"


def _edit_text(p):  # edited after drafting: hash no longer matches
    p["review"]["summary"] = "something else"


def _bad_version(p):
    p["hash_version"] = "2"


def _bad_reverts_shape(p):  # a valid-looking id that is not a plan id
    p["reverts_plan_id"] = "plan-abc_1"


def _traversal_reverts(p):
    p["reverts_plan_id"] = "../../etc/passwd"


@pytest.mark.parametrize("mutate,rehash", [
    (_drop_review, False), (_extra_key, False), (_edit_text, False), (_bad_version, False),
    (_bad_reverts_shape, True), (_traversal_reverts, True),
], ids=lambda v: getattr(v, "__name__", str(v)))
def test_malformed_or_tampered_review_is_marked_invalid(hub, mutate, rehash):
    port, tmp = hub
    plan_id = _tamper(mutate, rehash)(port, tmp)
    view = _pending(port)[plan_id]["review_view"]
    assert view["status"] == "invalid" and view["review"] is None and view["error"]


def test_integer_above_2_pow_53_is_refused_not_displayed_rounded(hub):
    """Hashed exactly by the hub, but a JavaScript page would show 9007199254740992."""
    port, tmp = hub
    plan = _draft(port, REVIEW)
    big = 2 ** 53 + 1

    def mutate(p):
        p["review"]["excluded"] = [{"element_id": big, "reason": "kept"}]
    _edit(tmp, plan["plan_id"], mutate)
    view = _pending(port)[plan["plan_id"]]["review_view"]
    assert view["status"] == "invalid" and "too large" in view["error"]


def test_legacy_v1_revert_plan_with_unhashed_content_is_invalid(hub):
    """A pre-upgrade revert plan keeps conflicts/warnings outside the hash; they are not
    shown, so the panel must not offer Approve."""
    port, tmp = hub
    plan = _draft(port)
    _edit(tmp, plan["plan_id"], lambda p: p.update(
        reverts_plan_id=REVERTED, conflicts=[{"element_id": 1}], warnings=["CONFLICT"]))
    got = _pending(port)[plan["plan_id"]]
    assert got["review_view"]["status"] == "invalid"
    assert "Legacy" in got["review_view"]["error"]


# ------------------------------------------- redaction must not change what is approved

REDACTION_CASES = {
    "path in a review warning": lambda port, tmp: _draft(port, {**REVIEW, "warnings": ["Also clears C:\\Levels and /etc/fire/plan.txt"]}),
    "password in the summary": lambda port, tmp: _draft(port, {**REVIEW, "summary": "password: hunter2 for the link"}),
    "path in a conflict value": lambda port, tmp: _draft(port, {**REVIEW, "conflicts": [
        {"element_id": 1, "parameter": "Link", "expected_current": "\\\\srv\\share\\a.rvt",
         "actual_current": "C:\\b.rvt", "revert_to": "D:\\c.rvt"}]}),
    "rhino_run_python code argument": lambda port, tmp: _draft(
        port, None, [{"tool": "rhino_run_python", "arguments": {"code": "import os; os.system('rm -rf ~')"}}]),
    "path inside an action argument": lambda port, tmp: _draft(
        port, None, [{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "Link", "value": "C:\\Users\\a\\x.rvt"}}]),
}


def _assembly_code_case(port, tmp):
    plan = _draft(port)
    _edit(tmp, plan["plan_id"], lambda p: p["actions"][0].setdefault("diff", {}).update(
        before={"1": {"Assembly Code": "A-100"}}))
    return plan


REDACTION_CASES["Assembly Code before value"] = _assembly_code_case


@pytest.mark.parametrize("name", list(REDACTION_CASES))
def test_content_changed_by_redaction_is_marked_invalid(hub, name):
    port, tmp = hub
    plan = REDACTION_CASES[name](port, tmp)
    got = _pending(port)[plan["plan_id"]]
    assert got["review_view"]["status"] == "invalid", got["review_view"]
    assert got["review_view"]["review"] is None
    assert "panel hides" in got["review_view"]["error"]


@pytest.mark.parametrize("name", list(REDACTION_CASES))
def test_real_hub_output_with_redacted_content_cannot_be_approved_in_the_page(hub, name):
    """Hub JSON goes through the real page code: Approve is off, nothing is sent, Reject works."""
    port, tmp = hub
    plan = REDACTION_CASES[name](port, tmp)
    plans = _list(port)["plans"]
    got = _run(f"""
host(); plans({json.dumps(plans)});
const html = els['plan-list'].innerHTML;
const approve = (html.match(/<button[^>]*data-decision="approve"[^>]*>/) || [''])[0];
sent.length = 0;
fire('click', {{ plan: {json.dumps(plan['plan_id'])}, decision: 'approve', hash: 'x' }});
fire('click', {{ plan: {json.dumps(plan['plan_id'])}, decision: 'reject', hash: 'x' }});
console.log(JSON.stringify({{ approve, sent, cli: html.includes('aec-model-bridge-approve') }}));
""")
    assert " disabled" in got["approve"], got
    assert [m["type"] for m in got["sent"]] == ["plan.reject"]


def test_unchanged_by_redaction_stays_approvable_and_matches_the_hash(hub):
    port, _ = hub
    plan = _draft(port, REVIEW)
    got = _pending(port)[plan["plan_id"]]
    assert got["review_view"]["status"] == "ok"
    assert got["review_view"]["review"] == proof.normalize_review(REVIEW)
    status, body = _approve(port, plan["plan_id"], got["plan_hash"])
    assert status == 200 and body["ok"]


def test_the_review_shown_equals_the_hashed_review_byte_for_byte(hub):
    port, tmp = hub
    plan = _draft(port, REVIEW)
    shown = _pending(port)[plan["plan_id"]]["review_view"]["review"]
    stored = json.loads(_plan_file(tmp, plan["plan_id"]).read_text("utf-8"))["review"]
    assert json.dumps(shown, sort_keys=True) == json.dumps(stored, sort_keys=True)
    assert redact_data(stored) == stored  # the benign fixture is untouched by redaction


# ---------------------------------------------------- the real MCP path is unchanged


@pytest.fixture
def mcp(tmp_path, monkeypatch):
    registry, approval, _jobs, _m, _w = build_registry(WorkspaceMonitor([tmp_path]))
    monkeypatch.setattr(mcp_server, "registry", registry, raising=False)
    monkeypatch.setattr(mcp_server, "approval_provider", approval, raising=False)
    return approval


def _mcp_call(name, arguments):
    out = asyncio.run(mcp_server.call_tool(name, arguments))
    return out[0].text


def test_mcp_list_pending_plans_has_no_review_view_and_keeps_the_raw_review(mcp):
    plan = asyncio.run(mcp.execute_tool("plan_actions", {
        "actions": [{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "A"}}],
        "review": REVIEW}))
    text = _mcp_call("list_pending_plans", {})
    listed = json.loads(text.split("Result:\n", 1)[1])["plans"]
    assert [p["plan_id"] for p in listed] == [plan["plan_id"]]
    assert "review_view" not in listed[0]
    assert listed[0]["review"] == proof.normalize_review(REVIEW)


@pytest.mark.parametrize("tool", ["approve_plan", "reject_plan", "rollback_plan"])
def test_decision_tools_are_refused_on_the_mcp_path_and_change_nothing(mcp, tool):
    plan = asyncio.run(mcp.execute_tool("plan_actions", {
        "actions": [{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "A"}}]}))
    text = _mcp_call(tool, {"plan_id": plan["plan_id"], "expected_hash": plan["plan_hash"]})
    assert "not available to AI clients" in text
    assert mcp.gate.load_plan(plan["plan_id"])["state"] == "pending"
    assert tool in HUMAN_ONLY_TOOLS
    assert tool not in {t.name for t in asyncio.run(mcp_server.list_tools())}


def test_panel_route_still_runs_the_human_decisions(hub):
    port, _ = hub
    approve_me = _draft(port, REVIEW)
    reject_me = _draft(port, REVIEW)
    status, body = _approve(port, approve_me["plan_id"], approve_me["plan_hash"])
    assert status == 200 and body["result"]["approved_via"] == "panel"
    status, body = _post(port, "/execute", {"tool": "reject_plan", "arguments": {"plan_id": reject_me["plan_id"]}})
    assert status == 200 and body["result"]["state"] == "rejected"


def test_panel_plans_does_not_mutate_its_input():
    plan = {"plan_id": "p1", "state": "pending", "actions": [], "review": copy.deepcopy(REVIEW)}
    before = copy.deepcopy(plan)
    out = proof.panel_plans({"plans": [plan]})
    assert plan == before
    assert out["plans"][0]["review_view"]["status"] == "invalid"  # no hash_version: inconsistent
    assert proof.panel_plans({"other": 1}) == {"other": 1}


# --------------------------------------------------------------- static panel guards


def _review_code() -> str:
    start = APP_JS.index("// ---- Plan review block")
    end = APP_JS.index("function planActionLines")
    return APP_JS[start:end]


def test_review_rendering_has_no_html_sink_and_no_links():
    code = re.sub(r"//[^\n]*", "", _review_code())
    for pattern in (r"innerHTML", r"outerHTML", r"insertAdjacentHTML", r"createContextualFragment",
                    r"<a[\s>]", r"\.href\b", r"window\.open", r"link\.open", r"postToHost", r"createElement\(\s*[\"']a[\"']"):
        assert not re.search(pattern, code), f"review rendering uses {pattern}"
    assert "textContent" in code


# ---------------------------------------------------- fail closed (node stub-DOM harness)


def _v2(plan_id="v2", **view):
    base = {"status": "ok", "hash_version": 2, "reverts_plan_id": None, "review": copy.deepcopy(REVIEW), "error": ""}
    base.update(view)
    return {"plan_id": plan_id, "state": "pending", "plan_hash": "h" * 16, "hash_version": 2,
            "actions": [{"tool": SET}], "review_view": base}


def _blocked_scenarios():
    bad_review = copy.deepcopy(REVIEW)
    bad_review["citations"] = "not a list"
    wrong_type = copy.deepcopy(REVIEW)
    wrong_type["warnings"] = [{"x": 1}]
    too_many = copy.deepcopy(REVIEW)
    too_many["warnings"] = ["w"] * 101
    unsafe = copy.deepcopy(REVIEW)
    unsafe["excluded"] = [{"element_id": 2 ** 53, "reason": "x"}]
    no_view = _v2()
    del no_view["review_view"]
    return {
        "missing view": no_view,
        "status invalid": _v2(status="invalid", review=None, error="bad"),
        "review null": _v2(review=None),
        "citations not list": _v2(review=bad_review),
        "warning wrong type": _v2(review=wrong_type),
        "list over the cap": _v2(review=too_many),
        "integer above 2^53": _v2(review=unsafe),
        "hub says none for a v2 plan": _v2(status="none", review=None),
        "wrong hash version": _v2(hash_version=3),
        "reverts id not a plan id": _v2(reverts_plan_id="plan-abc_1"),
        "reverts id not a string": _v2(reverts_plan_id=7),
    }


@pytest.mark.parametrize("name", list(_blocked_scenarios()))
def test_unshowable_v2_review_disables_approve(name):
    plan = _blocked_scenarios()[name]
    got = _run(f"""
host(); plans([{json.dumps(plan)}]);
const html = els['plan-list'].innerHTML;
const approve = (html.match(/<button[^>]*data-decision="approve"[^>]*>/) || [''])[0];
sent.length = 0;
fire('click', {{ plan: 'v2', decision: 'approve', hash: 'x' }});
fire('change', {{ selectPlan: 'v2', checked: 'true' }});
fire('click', {{ action: 'approve-selected' }});
fire('click', {{ plan: 'v2', decision: 'reject', hash: 'x' }});
console.log(JSON.stringify({{ approve, sent, checkbox: html.includes('data-select-plan') }}));
""")
    assert " disabled" in got["approve"] and 'data-review-blocked="1"' in got["approve"], got
    assert not any(m["type"] == "plan.approve" for m in got["sent"]), "an unshowable plan was approved"
    assert got["checkbox"] is False
    assert [m["type"] for m in got["sent"]] == ["plan.reject"], "Reject must stay available"


def test_v2_plan_waits_for_its_review_to_be_opened_and_v1_does_not():
    v1 = {"plan_id": "v1", "state": "pending", "plan_hash": "a", "actions": [{"tool": "a"}]}
    got = _run(f"""
host(); plans([{json.dumps(_v2())}, {json.dumps(v1)}]);
const html = els['plan-list'].innerHTML;
console.log(JSON.stringify({{ buttons: html.match(/<button[^>]*data-decision="approve"[^>]*>/g) }}));
""")
    v2_button, v1_button = got["buttons"]
    assert " disabled" in v2_button, "a v2 plan must not be approvable before its review is opened"
    assert " disabled" not in v1_button
