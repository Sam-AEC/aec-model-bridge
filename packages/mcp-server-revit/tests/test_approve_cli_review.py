"""aec-model-bridge-approve: the per-action review table, --show, --all, --json and --color."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from revit_mcp_server import approve_cli, approve_review
from revit_mcp_server.approve_review import color_supported, display_width, render_review, wrap_cell
from revit_mcp_server.security.approval import ApprovalGate, plan_hash

SET = "revit_set_parameter_value"


def _set(element, param, value):
    key = "element_ids" if isinstance(element, list) else "element_id"
    return {"tool": SET, "arguments": {key: element, "parameter_name": param, "value": value}}


@pytest.fixture
def gate(tmp_path, monkeypatch):
    g = ApprovalGate(tmp_path, "ask_first", pending_ttl=3600)
    monkeypatch.setattr(approve_cli, "_gate", lambda ws: g)
    monkeypatch.setattr(approve_review, "terminal_width", lambda default=100: 100)
    monkeypatch.setattr(approve_cli, "terminal_width", lambda default=100: 100)
    return g


def _show(gate, pid, *extra, capsys):
    assert approve_cli.main(["--workspace", str(gate.workspace_dir), "--show", pid, *extra]) == 0
    return capsys.readouterr().out


def _review(gate, pid, **kw):
    plan = gate.load_plan(pid)
    review = approve_review.build_review(plan, gate, plan_hash(plan), gate.expiry_reason(plan))
    return review, render_review(review, **kw)


def test_single_parameter_write_shows_old_and_new_value(gate, capsys):
    pid = gate.create_plan([_set(77, "FireRating", "60")], [{"77": {"FireRating": "30"}}])["plan_id"]
    out = _show(gate, pid, capsys=capsys)
    row = next(line for line in out.splitlines() if line.strip().startswith("77"))
    assert "FireRating" in row and "30" in row and "-> 60" in row
    full = plan_hash(gate.load_plan(pid))
    assert f"Plan hash: {full[:19]} (short" in out and f"Plan hash: {full}" in out
    assert "Approval mode: ask_first" in out
    assert "Expiry: " in out and "pending_ttl 1 h" in out
    assert "Document: no binding recorded" in out
    assert "Actions: 1   Elements: 1   Parameters: 1" in out and "Changes: 1 (old value captured for 1)" in out
    assert "\x1b" not in out


def test_element_name_and_mark_come_from_the_snapshot(gate, capsys):
    snaps = gate.workspace_dir / "snapshots"
    snaps.mkdir()
    (snaps / "snap_1.json").write_text(json.dumps({"elements": [
        {"element_id": 77, "uid": "u-77", "name": "Single-Flush", "params": {"Mark": {"v": "D-101", "storage": "String"}}},
    ]}), encoding="utf-8")
    pid = gate.create_plan([_set(77, "FireRating", "60")], [{"77": {"FireRating": "30"}}], snapshot_id="snap_1")["plan_id"]
    assert "77 (Single-Flush, Mark D-101)" in _show(gate, pid, capsys=capsys)
    review, _ = _review(gate, pid)
    change = review["actions"][0]["changes"][0]
    assert change["element_name"] == "Single-Flush" and change["mark"] == "D-101" and change["unique_id"] == "u-77"


def test_old_value_not_captured_is_said_and_warned(gate, capsys):
    pid = gate.create_plan([_set(5, "Comments", "x")], [{}])["plan_id"]
    out = _show(gate, pid, capsys=capsys)
    assert "(not captured)" in out and "Old value not captured for 1 change(s)." in out


def test_many_elements_are_truncated_with_a_use_all_line(gate, capsys):
    ids = list(range(1000, 1080))
    pid = gate.create_plan([_set(ids, "Comments", "checked")], [{str(i): {"Comments": ""} for i in ids}])["plan_id"]
    out = _show(gate, pid, capsys=capsys)
    rows = [ln for ln in out.splitlines() if ln.strip()[:4].isdigit() and "Comments" in ln]
    assert len(rows) == approve_review.DEFAULT_MAX_ROWS
    assert f"+{80 - approve_review.DEFAULT_MAX_ROWS} more row(s)" in out and "use --all" in out
    assert "Elements: 80" in out
    out_all = _show(gate, pid, "--all", capsys=capsys)
    assert len([ln for ln in out_all.splitlines() if ln.strip()[:4].isdigit() and "Comments" in ln]) == 80
    assert "use --all" not in out_all


def test_many_actions_are_truncated_and_counted(gate, capsys):
    acts = [_set(i, "Mark", f"M-{i}") for i in range(1, 51)]
    pid = gate.create_plan(acts, [{} for _ in acts])["plan_id"]
    out = _show(gate, pid, capsys=capsys)
    assert "Action 30/50" in out and "Action 31/50" not in out
    assert "+20 more row(s), 20 more action(s) not shown, use --all" in out
    assert "Action 50/50" in _show(gate, pid, "--all", capsys=capsys)


def test_nested_values_print_as_compact_sorted_json(gate, capsys):
    value = {"z": [1, 2, {"c": None}], "a": {"b": True}}
    pid = gate.create_plan([_set(9, "Data", value),
                            {"tool": "revit_create_wall", "arguments": {"level": "L1", "points": [[0, 0], [5, 0]]}}],
                           [{"9": {"Data": {"a": {"b": False}}}}, {}])["plan_id"]
    out = _show(gate, pid, "--all", capsys=capsys)
    assert '{"a": {"b": false}}' in out
    assert '{"a": {"b": true}, "z": [1, 2, {"c": null}]}' in out
    assert "(no element named)" in out and '"level": "L1"' in out


def test_unicode_values_and_wide_characters_wrap_by_display_width(gate):
    text = "Überprüft 检查完毕 " * 20
    pid = gate.create_plan([_set(3, "Kommentar", text)], [{"3": {"Kommentar": "café"}}])["plan_id"]
    _, out = _review(gate, pid, width=72)
    assert "café" in out and "Überprüft 检查完毕" in out
    assert all(display_width(ln) <= 72 for ln in out.splitlines())
    _, narrow = _review(gate, pid, width=60)
    assert all(display_width(ln) <= 60 for ln in narrow.splitlines())
    assert all(display_width(ln) <= 7 for ln in wrap_cell("检查完毕检查完毕", 7))


def test_very_long_strings_are_wrapped_and_cut_unless_all(gate):
    text = "A" * 1500 + " end-marker"
    pid = gate.create_plan([_set(4, "Comments", text)], [{"4": {"Comments": "short"}}])["plan_id"]
    _, out = _review(gate, pid, width=80)
    assert all(display_width(ln) <= 80 for ln in out.splitlines())
    assert f"(+{len(text) - approve_review.VALUE_MAX_CHARS} chars, use --all)" in out
    assert "end-marker" not in out
    _, out_all = _review(gate, pid, width=80, show_all=True)
    assert all(display_width(ln) <= 80 for ln in out_all.splitlines())
    assert "end-marker" in out_all and "use --all" not in out_all
    assert "".join(ln.strip() for ln in out_all.splitlines()).count("A") >= 1500


def test_model_text_in_values_and_names_is_escaped(gate, capsys):
    snaps = gate.workspace_dir / "snapshots"
    snaps.mkdir()
    (snaps / "s.json").write_text(json.dumps({"elements": [{"element_id": 8, "name": "\x1b]0;x\x07Door"}]}), encoding="utf-8")
    pid = gate.create_plan([_set(8, "Comments\x1b[2K", "ok\r\x1b[1Afake line‮")], [{}], snapshot_id="s")["plan_id"]
    out = _show(gate, pid, capsys=capsys)
    for raw in ("\x1b", "\r", "\x07", "‮"):
        assert raw not in out
    assert "\\x1b[2K" in out and "\\x0d" in out


def test_show_never_changes_the_plan_or_the_store(gate, capsys):
    pid = gate.create_plan([_set(77, "FireRating", "60")], [{"77": {"FireRating": "30"}}])["plan_id"]
    path = gate.plans_dir / f"{pid}.json"
    before = path.read_bytes()
    listing = sorted(p.relative_to(gate.workspace_dir) for p in gate.workspace_dir.rglob("*"))
    ws = ["--workspace", str(gate.workspace_dir)]
    for argv in (["--show", pid], ["--show", pid, "--all"], ["--show", pid, "--json"], ["show", pid, "--json"],
                 ["show", pid, "--all", "--color"]):
        assert approve_cli.main(ws + argv) == 0
    capsys.readouterr()
    assert path.read_bytes() == before
    assert gate.load_plan(pid)["state"] == "pending"
    assert sorted(p.relative_to(gate.workspace_dir) for p in gate.workspace_dir.rglob("*")) == listing


def test_json_review_schema(gate, capsys):
    pid = gate.create_plan([_set([1, 2], "Mark", "W-1"), {"tool": "revit_create_wall", "arguments": {"level": "L1"}}],
                           [{"1": {"Mark": ""}}, {}],
                           binding={"doc_title": "Tower.rvt", "revit_version": "2024", "doc_guid": "g"})["plan_id"]
    out = _show(gate, pid, "--json", capsys=capsys)
    data = json.loads(out)  # stdout is only the JSON document
    assert data["schema"] == "aec-model-bridge/plan-review" and data["schema_version"] == 1
    assert set(data) >= {"plan_id", "state", "created_at", "plan_hash", "plan_hash_short", "approval_mode", "expiry",
                         "binding", "counts", "tools", "risk", "warnings", "approvable", "not_approvable_reasons",
                         "actions", "review", "not_hashed_keys"}
    assert data["plan_hash"] == plan_hash(gate.load_plan(pid))
    assert data["plan_hash_short"] == data["plan_hash"][:19]
    assert data["approval_mode"]["mode"] == "ask_first"
    assert data["expiry"]["rule"] == "pending_ttl" and data["expiry"]["ttl_seconds"] == 3600
    assert datetime.fromisoformat(data["expiry"]["expires_at"])
    assert data["binding"] == {"recorded": True, "bound": True, "doc_title": "Tower.rvt", "revit_version": "2024",
                               "active_view_id": None}
    assert data["counts"] == {"actions": 2, "elements": 2, "parameters": 1, "changes": 3, "old_values_captured": 1}
    assert data["approvable"] is True and data["not_approvable_reasons"] == []
    first, wall = data["actions"]
    assert [c["element_id"] for c in first["changes"]] == ["1", "2"]
    assert first["changes"][0] == {"element_id": "1", "element_name": None, "mark": None, "unique_id": None,
                                   "parameter": "Mark", "old": "", "old_captured": True, "new": "W-1",
                                   "new_is_arguments": False}
    assert first["changes"][1]["old_captured"] is False
    assert wall["changes"][0]["element_id"] is None and wall["changes"][0]["new"] == {"level": "L1"}
    assert all(w.keys() == {"source", "text"} for w in data["warnings"])


def test_json_escapes_control_characters(gate, capsys):
    pid = gate.create_plan([_set(1, "C", "\x1b[31mred")], [{}])["plan_id"]
    out = _show(gate, pid, "--json", capsys=capsys)
    assert "\x1b" not in out and json.loads(out)["actions"][0]["changes"][0]["new"] == "\x1b[31mred"


def test_expired_and_unbound_plans_are_flagged(gate, capsys):
    pid = gate.create_plan([_set(1, "C", "v")], [{}], binding=None)["plan_id"]
    stored = gate.load_plan(pid)
    stored["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    gate.save_plan(stored)
    out = _show(gate, pid, capsys=capsys)
    assert "EXPIRED:" in out and "NOT BOUND" in out
    data = json.loads(_show(gate, pid, "--json", capsys=capsys))
    assert data["approvable"] is False and "expired" in data["not_approvable_reasons"]
    assert data["expiry"]["expired"] is True and data["binding"] == {"recorded": True, "bound": False}


def test_malformed_action_is_shown_as_malformed(gate):
    pid = gate.create_plan([_set(1, "C", "v")], [{}])["plan_id"]
    path = gate.plans_dir / f"{pid}.json"
    data = json.loads(path.read_text())
    data["actions"][0]["arguments"] = ["dry run"]
    path.write_text(json.dumps(data))
    plan = gate.load_plan(pid)
    review = approve_review.build_review(plan, gate, plan_hash(plan), None, approve_cli.malformed_reasons(plan))
    assert "MALFORMED ARGUMENTS" in render_review(review) and review["approvable"] is False


# ---- confirmation is unchanged ------------------------------------------------------------


def _tty(monkeypatch, typed):
    stdin = io.StringIO(typed + "\n")
    stdin.isatty = lambda: True
    monkeypatch.setattr("sys.stdin", stdin)


def test_approve_still_needs_the_typed_plan_id(gate, monkeypatch, capsys):
    pid = gate.create_plan([_set(77, "FireRating", "60")], [{"77": {"FireRating": "30"}}])["plan_id"]
    ws = ["--workspace", str(gate.workspace_dir)]
    _tty(monkeypatch, "y")
    assert approve_cli.main(ws + ["approve", pid, "--all"]) == 2
    assert gate.load_plan(pid)["state"] == "pending"
    out = capsys.readouterr().out
    assert "-> 60" in out and "Type the plan id" in out
    _tty(monkeypatch, pid)
    assert approve_cli.main(ws + ["approve", pid]) == 0
    assert gate.load_plan(pid)["state"] == "approved"


def test_a_cut_down_review_cannot_be_approved(gate, monkeypatch, capsys):
    ids = list(range(1, 41))
    pid = gate.create_plan([_set(ids, "C", "v")], [{}])["plan_id"]
    _tty(monkeypatch, pid)
    # A cut-down review cannot be approved, even with the right plan id typed.
    assert approve_cli.main(["approve", pid]) == 1
    assert f"approve {pid} --all` to see every row and approve" in capsys.readouterr().err
    assert gate.load_plan(pid)["state"] == "pending"
    _tty(monkeypatch, "no")
    assert approve_cli.main(["approve", pid, "--all"]) == 2
    assert "was not printed above" not in capsys.readouterr().out
    small = gate.create_plan([_set(1, "C", "v")], [{}])["plan_id"]
    _tty(monkeypatch, "no")
    assert approve_cli.main(["approve", small]) == 2
    assert "was not printed above" not in capsys.readouterr().out


def test_approve_without_a_terminal_still_refuses(gate, monkeypatch, capsys):
    pid = gate.create_plan([_set(1, "C", "v")], [{}])["plan_id"]
    monkeypatch.setattr("sys.stdin", io.StringIO(pid + "\n"))
    assert approve_cli.main(["--workspace", str(gate.workspace_dir), "approve", pid, "--all"]) == 2
    assert "without a terminal" in capsys.readouterr().err
    assert gate.load_plan(pid)["state"] == "pending"


@pytest.mark.parametrize("argv", [
    ["approve", "PID", "--json"],         # --json is review only
    ["--show", "PID", "approve", "PID"],  # --show is not combined with a command
    [],                                   # a command or --show is needed
    ["--all", "list"],                    # review options go after the command
    ["reject", "--all-pending", "--all"],
])
def test_review_options_are_checked(gate, argv, capsys):
    pid = gate.create_plan([_set(1, "C", "v")], [{}])["plan_id"]
    argv = [pid if a == "PID" else a for a in argv]
    with pytest.raises(SystemExit) as exc:
        approve_cli.main(["--workspace", str(gate.workspace_dir), *argv])
    assert exc.value.code == 2
    assert gate.load_plan(pid)["state"] == "pending"


# ---- color ----------------------------------------------------------------------------------


class _Stream:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.mark.parametrize("tty,env,os_name,expected", [
    (True, {"TERM": "xterm-256color"}, "posix", True),
    (True, {"TERM": "xterm", "NO_COLOR": "1"}, "posix", False),
    (True, {"TERM": "xterm", "NO_COLOR": ""}, "posix", True),
    (False, {"TERM": "xterm"}, "posix", False),
    (True, {"TERM": "dumb"}, "posix", False),
    (True, {}, "posix", False),
    (True, {}, "nt", False),                  # classic cmd.exe: no ANSI
    (True, {"WT_SESSION": "x"}, "nt", True),  # Windows Terminal
    (True, {"WT_SESSION": "x", "NO_COLOR": "1"}, "nt", False),
])
def test_color_only_when_supported_and_no_color_unset(tty, env, os_name, expected):
    assert color_supported(_Stream(tty), env, os_name) is expected


def test_color_is_off_by_default_and_off_when_not_a_terminal(gate, capsys):
    pid = gate.create_plan([_set(1, "C", "v")], [{}])["plan_id"]
    review, plain = _review(gate, pid)
    assert "\x1b" not in plain and "\x1b[" in render_review(review, color=True)
    assert "\x1b" not in _show(gate, pid, "--color", capsys=capsys)  # captured stdout is not a terminal


# ---- every execution-relevant argument is shown ---------------------------------------------

BY_FILTER = "revit_batch_set_parameters_by_filter"


def _by_filter(flt):
    return {"tool": BY_FILTER, "arguments": {"filter": flt, "parameter_name": "Comments", "value": "checked"}}


def test_filter_of_a_parameter_write_is_shown_and_changes_the_review(gate):
    walls = gate.create_plan([_by_filter({"category": "Walls", "level": "L1"})], [{}])["plan_id"]
    doors = gate.create_plan([_by_filter({"category": "Doors", "level": "L1"})], [{}])["plan_id"]
    review_w, out_w = _review(gate, walls)
    review_d, out_d = _review(gate, doors)
    assert 'Other arguments: {"filter": {"category": "Walls", "level": "L1"}}' in out_w
    assert '"Doors"' in out_d and '"Doors"' not in out_w
    strip = lambda out: [ln for ln in out.splitlines() if not ln.startswith(("Plan ", "Created", "Expiry"))]  # noqa: E731
    assert strip(out_w) != strip(out_d)
    assert review_w["actions"][0]["other_arguments"] == {"filter": {"category": "Walls", "level": "L1"}}
    assert approve_review.is_cut(review_w) is False


def test_a_long_other_argument_is_cut_and_needs_all(gate):
    flt = {"category": "Walls", "parameter_filter": {"name": "Comments", "value": "x" * 400 + " tail-marker"}}
    pid = gate.create_plan([_by_filter(flt)], [{}])["plan_id"]
    review, out = _review(gate, pid)
    assert "tail-marker" not in out and "use --all" in out
    assert approve_review.is_cut(review) is True
    _, out_all = _review(gate, pid, show_all=True)
    assert "tail-marker" in out_all


def test_id_keys_not_in_the_element_column_are_other_arguments(gate):
    # element_ids is the list the Element column shows; the second list key is not shown there.
    action = {"tool": SET, "arguments": {"element_ids": [1], "ids": [2, 3], "parameter_name": "Mark", "value": "v"}}
    pid = gate.create_plan([action], [{}])["plan_id"]
    review, out = _review(gate, pid)
    assert review["actions"][0]["other_arguments"] == {"ids": [2, 3]}
    assert 'Other arguments: {"ids": [2, 3]}' in out
    plain = gate.create_plan([_set(5, "Mark", "v")], [{}])["plan_id"]
    review, out = _review(gate, plain)
    assert review["actions"][0]["other_arguments"] == {} and "Other arguments" not in out
