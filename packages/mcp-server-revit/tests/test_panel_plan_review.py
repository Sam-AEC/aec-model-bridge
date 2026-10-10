"""The panel shows the plan's hashed review block, and fails closed when it cannot.

Covers the hub payload (``review_view`` on the panel's list_pending_plans route only),
static guards on panel/app.js (no HTML sink for review text, no links), and the fail-closed
rule in a node stub-DOM harness. Browser behaviour is in tests/panel_web/app_driver.js.
"""
from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path

import pytest

from revit_mcp_server.panel_server import build_server
from revit_mcp_server.security import proof
from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS, ApprovalGate, plan_hash
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_panel_a11y import HARNESS, _run  # noqa: F401  (stub-DOM harness)
from test_panel_server import _post

APP_JS = (Path(__file__).resolve().parents[3] / "panel" / "app.js").read_text(encoding="utf-8")
SET = "revit_set_parameter_value"

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


def _draft(port, review=None):
    args = {"actions": [{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "A"}}]}
    if review is not None:
        args["review"] = review
    status, body = _post(port, "/execute", {"tool": "plan_actions", "arguments": args})
    assert status == 200, body
    return body["result"]


def _pending(port):
    status, body = _post(port, "/execute", {"tool": "list_pending_plans", "arguments": {}})
    assert status == 200
    return {p["plan_id"]: p for p in body["result"]["plans"]}


def _plan_file(tmp_path, plan_id):
    matches = list(tmp_path.rglob(f"plans/{plan_id}.json"))
    assert len(matches) == 1
    return matches[0]


# ------------------------------------------------------------------ hub payload


def test_panel_payload_carries_normalised_review_version_and_reverts_id(hub):
    port, tmp = hub
    plan = _draft(port, REVIEW)
    path = _plan_file(tmp, plan["plan_id"])
    stored = json.loads(path.read_text("utf-8"))
    stored["reverts_plan_id"] = "plan-abc_1"
    stored["plan_hash"] = plan_hash(stored)
    path.write_text(json.dumps(stored), "utf-8")
    got = _pending(port)[plan["plan_id"]]
    view = got["review_view"]
    assert view["status"] == "ok" and view["hash_version"] == 2
    assert view["review"] == proof.normalize_review(REVIEW)
    assert view["reverts_plan_id"] == "plan-abc_1"
    assert "review" not in got, "the panel must read only the validated copy"
    assert got["plan_hash"] == stored["plan_hash"]


def test_plan_without_review_is_version_one_none(hub):
    port, _ = hub
    plan = _draft(port)
    view = _pending(port)[plan["plan_id"]]["review_view"]
    assert view["status"] == "none" and view["hash_version"] == 1 and view["review"] is None


def _tamper(mutate):
    def go(port, tmp):
        plan = _draft(port, REVIEW)
        path = _plan_file(tmp, plan["plan_id"])
        stored = json.loads(path.read_text("utf-8"))
        mutate(stored)
        path.write_text(json.dumps(stored), "utf-8")
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


def _bad_reverts(p):
    p["reverts_plan_id"] = "../../etc/passwd"
    p["plan_hash"] = proof.plan_content_hash(p)


@pytest.mark.parametrize("mutate", [_drop_review, _extra_key, _edit_text, _bad_version, _bad_reverts],
                         ids=lambda f: f.__name__)
def test_malformed_or_tampered_review_is_marked_invalid(hub, mutate):
    port, tmp = hub
    plan_id = _tamper(mutate)(port, tmp)
    got = _pending(port)[plan_id]
    assert got["review_view"]["status"] == "invalid"
    assert got["review_view"]["review"] is None
    assert got["review_view"]["error"]


def test_review_view_is_added_only_on_the_panel_route(hub):
    """The generic tool path (MCP clients, chat) is unchanged and learns nothing new."""
    port, tmp = hub
    _draft(port, REVIEW)
    gate = ApprovalGate(next(tmp.rglob("plans")).parent, "required")
    for plan in gate.list_pending_plans():
        assert "review_view" not in plan


def test_approve_and_reject_remain_human_only():
    assert {"approve_plan", "reject_plan", "rollback_plan"} <= HUMAN_ONLY_TOOLS
    assert "list_pending_plans" not in HUMAN_ONLY_TOOLS
    from revit_mcp_server import panel_server

    assert "review_view" not in Path(panel_server.__file__).read_text("utf-8").split("def _run_tool_sync")[1].split("APPROVAL_MODE_NOTES")[0]


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


def test_review_text_is_escaped_and_clipped():
    code = _review_code()
    assert "visibleText(raw)" in code, "review text must go through visibleText"
    assert "Show more" in code and "REVIEW_CLIP" in code


def test_every_review_field_is_rendered():
    code = _review_code()
    for needle in ("r.summary", "r.reasoning", "c.rule_id", "c.clause", "c.source", "r.assumptions",
                   "x.element_id", "x.reason", "r.warnings", "c.parameter", "c.expected_current",
                   "c.actual_current", "c.revert_to", "revertsPlanId"):
        assert needle in code, needle


def test_hash_coverage_is_stated_on_the_card():
    assert "Covered by the approval hash" in _review_code()


def test_blocked_message_names_the_cli_fallback():
    assert "aec-model-bridge-approve show" in _review_code()


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
    no_view = _v2()
    del no_view["review_view"]
    return {
        "missing view": no_view,
        "status invalid": _v2(status="invalid", review=None, error="bad"),
        "review null": _v2(review=None),
        "citations not list": _v2(review=bad_review),
        "warning wrong type": _v2(review=wrong_type),
        "hub says none for a v2 plan": _v2(status="none", review=None),
        "wrong hash version": _v2(hash_version=3),
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
console.log(JSON.stringify({{ approve, sent, checkbox: html.includes('data-select-plan'),
  message: html.includes('plan-review') }}));
""")
    assert " disabled" in got["approve"] and 'data-review-blocked="1"' in got["approve"], got
    assert not any(m["type"] == "plan.approve" for m in got["sent"]), "an unshowable plan was approved"
    assert got["checkbox"] is False
    assert [m["type"] for m in got["sent"]] == ["plan.reject"], "Reject must stay available"


def test_valid_v2_and_v1_plans_stay_approvable():
    v1 = {"plan_id": "v1", "state": "pending", "plan_hash": "a", "actions": [{"tool": "a"}]}
    got = _run(f"""
host(); plans([{json.dumps(_v2())}, {json.dumps(v1)}]);
const html = els['plan-list'].innerHTML;
const approveButtons = html.match(/<button[^>]*data-decision="approve"[^>]*>/g);
console.log(JSON.stringify({{ buttons: approveButtons }}));
""")
    assert len(got["buttons"]) == 2
    assert not any("disabled" in b for b in got["buttons"])
