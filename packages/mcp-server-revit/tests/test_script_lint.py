"""Advisory lint for revit_execute_python scripts. It warns; it never blocks or changes a script."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from revit_mcp_server.providers.revit import BridgeMode, RevitProvider
from revit_mcp_server.security import plan_review as pr
from revit_mcp_server.security import proof as proof_mod
from revit_mcp_server.security.read_mode import execute_python_payload
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.script_lint import RULES, lint_script

# rule id -> (script that must trigger it, script that must not)
FIXTURES = {
    "collections_import": (
        "from collections import defaultdict\nd = defaultdict(list)\n",
        "d = {}\nd.setdefault('a', []).append(1)\n",
    ),
    "fstring": (
        "print(f'walls: {n}')\n",
        "print('walls: %d' % n)\nprint('of' 'fer')\n",
    ),
    "out_parameter_roof": (
        "roof = doc.Create.NewFootPrintRoof(profile, level, rtype, mapping)\n",
        "# use revit.create_roof for roofs\nprint(doc.Title)\n",
    ),
    "wall_flip": (
        "wall = doc.GetElement(eid)\nwall.Flip()\n",
        "curve = curve.CreateReversed()\n",
    ),
    "phase_indexer": (
        "room = door.FromRoom\n",
        "room = door.get_FromRoom(phase)\nx = Autodesk.Revit.DB.Architecture.Room\n",
    ),
    "transaction_unclosed": (
        "t = Transaction(doc, 'x')\nt.Start()\nwall.Location.Move(v)\n",
        "t = Transaction(doc, 'x')\nt.Start()\ntry:\n    pass\n    t.Commit()\nexcept:\n    t.RollBack()\n",
    ),
    "family_doc_not_closed_in_finally": (
        "fdoc = doc.EditFamily(fam)\nfdoc.Close(False)\n",
        "fdoc = doc.EditFamily(fam)\ntry:\n    pass\nfinally:\n    fdoc.Close(False)\n",
    ),
    "dialog_blocks_bridge": (
        "TaskDialog.Show('Done', 'ok')\n",
        "print('Done')\n",
    ),
    "long_sleep": (
        "import time\ntime.sleep(40)\n",
        "import time\ntime.sleep(2)\n",
    ),
}


def _ids(script):
    return {w["rule"] for w in lint_script(script)}


def test_every_rule_has_a_message_an_example_and_a_fixture_pair():
    assert {r.id for r in RULES} == set(FIXTURES)
    for rule in RULES:
        assert rule.message and rule.example
        assert not hasattr(rule, "blocking")  # advisory only


@pytest.mark.parametrize("rule_id", sorted(FIXTURES))
def test_failing_fixture_triggers_only_its_rule(rule_id):
    bad, _ = FIXTURES[rule_id]
    assert rule_id in _ids(bad)


@pytest.mark.parametrize("rule_id", sorted(FIXTURES))
def test_passing_fixture_is_clean_for_its_rule(rule_id):
    _, good = FIXTURES[rule_id]
    assert rule_id not in _ids(good)


def test_warning_shape_and_line_number():
    (warning,) = [w for w in lint_script("x = 1\n\nwall.Flip()\n") if w["rule"] == "wall_flip"]
    assert warning["line"] == 3
    assert warning["message"] and warning["example"]


def test_comments_are_ignored():
    assert lint_script("# wall.Flip() breaks joins\nprint(1)\n") == []


@pytest.mark.parametrize("bad", [None, "", "   ", 5, b"x"])
def test_non_script_input_gives_no_warnings(bad):
    assert lint_script(bad) == []


def test_python2_syntax_does_not_stop_the_lint():
    assert "wall_flip" in _ids("print 'hi'\nwall.Flip()\n")


def test_lint_does_not_change_the_payload_or_read_mode():
    script = "from collections import deque\nwall.Flip()\n"
    assert execute_python_payload({"script": script}) == {"script": script, "mode": "write"}


def _provider(tmp_path):
    return RevitProvider(workspace=WorkspaceMonitor([Path(tmp_path)]), mode=BridgeMode.mock)


def test_tool_result_carries_warnings_and_still_runs(tmp_path):
    provider = _provider(tmp_path)
    plain = asyncio.run(provider.execute_tool("revit_execute_python", {"script": "print(1)"}))
    assert "lint_warnings" not in plain
    linted = asyncio.run(provider.execute_tool("revit_execute_python", {"script": "wall.Flip()"}))
    assert [w["rule"] for w in linted["lint_warnings"]] == ["wall_flip"]
    assert set(linted) - {"lint_warnings"} == set(plain)


def _plan(script):
    return {"actions": [{"action_id": "a", "tool": "revit_execute_python",
                         "arguments": {"script": script, "mode": "write"},
                         "diff": {"before": {}, "after": {"script": script}}}]}


def test_plan_preview_lists_warnings_without_touching_the_plan():
    plan = _plan("wall.Flip()\n")
    aids = pr.review_aids(plan)
    assert aids["script_lint"][0]["action_id"] == "a"
    assert aids["script_lint"][0]["rule"] == "wall_flip"
    assert "wall_flip" in aids["preview_markdown"] and "Script lint" in aids["preview_markdown"]
    assert "script_lint" in proof_mod.DERIVED_PLAN_KEYS
    assert "script_lint" not in plan


def test_plan_preview_has_no_lint_section_for_a_clean_script_or_other_tools():
    assert "script_lint" not in pr.review_aids(_plan("print(1)\n"))
    other = {"actions": [{"action_id": "a", "tool": "revit_set_parameter_value",
                          "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "x"},
                          "diff": {"before": {}, "after": {}}}]}
    assert "script_lint" not in pr.review_aids(other)
