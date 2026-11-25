"""Caller-supplied ids and paths must never name a file outside the folder that owns them.

Every store entry point that builds a file name from a plan id, recipe id, proof id,
request id or snapshot id goes through security/safe_paths.safe_child; the workspace
sandbox resolves paths with os.path.realpath. These tests throw hostile ids at all of them.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from revit_mcp_server.errors import BridgeError, WorkspaceViolation
from revit_mcp_server.security import proof as proof_mod
from revit_mcp_server.security.approval import ApprovalGate, plan_hash
from revit_mcp_server.security.recipe_store import ID_RE, RecipeError, RecipeStore
from revit_mcp_server.security.safe_paths import PLAN_ID_RE, SNAPSHOT_ID_RE, safe_child, snapshot_file
from revit_mcp_server.security.workspace import WorkspaceMonitor, is_reserved_path

SET = "revit_set_parameter_value"
VALID_PLAN = "plan_0123456789ab"
READ_CODE = "def main():\n    summary('read ok')\n    row([('n', 1)])\n\n\n__output__ = run_main(main)\n"

# Shared hostile shapes. Mixed case and look-alike Unicode are refused by the strict
# plan/recipe/snapshot shapes (the proof id shape is wider on case, so it has its own list).
TRAVERSAL = [
    "../x", "..\\x", "..", ".", "a/../b", "/etc/passwd", "\\windows\\x", "C:\\Windows\\x", "C:x", "c:/x",
    "\\\\server\\share\\x", "//server/share/x", "x\x00y", "", " ", "x" * 500, "a b", "a.b", "a:b", "con.txt",
    "x\n", "\ufb01", "\u202e", "\u0430bc", "\uff10\uff11", "\u00e9", None, 5, b"x", ["x"],
]
PLAN_BAD = TRAVERSAL + [
    "PLAN_0123456789AB", "plan_0123456789AB", "Plan_0123456789ab", "plan_0123456789ab\n", "plan_0123456789ab ",
    "plan_0123456789ab.json", "plan_0123456789a", "plan_0123456789abc", "plan_\uff10123456789ab",
    "pl\u0430n_0123456789ab", "plan_0123456789ab\x00",
]
RECIPE_BAD = TRAVERSAL + ["A", "Abc", "con", "nul", "com1", "lpt9", "a" * 65]
SNAPSHOT_BAD = TRAVERSAL + ["x" * 65]


def _link(target: Path, link: Path) -> None:
    """Symlink (or a junction for a folder on Windows); skip the test when neither is allowed."""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32" and target.is_dir():
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if done.returncode == 0:
            return
    pytest.skip("cannot create a symlink or junction here")


# ---- safe_child itself -------------------------------------------------------------


def _refuse(reason):
    return ValueError(reason)


def test_safe_child_accepts_a_plain_name_and_stays_inside(tmp_path):
    path = safe_child(tmp_path, "plan_0123456789ab", ".json", PLAN_ID_RE, _refuse)
    assert path == Path(os.path.realpath(tmp_path)) / "plan_0123456789ab.json"
    sub = safe_child(tmp_path, "plan_0123456789ab", ".lock", PLAN_ID_RE, _refuse, subdir=".locks")
    assert sub.parent.name == ".locks" and sub.name == "plan_0123456789ab.lock"


@pytest.mark.parametrize("bad", PLAN_BAD)
def test_safe_child_refuses_hostile_names(tmp_path, bad):
    with pytest.raises(ValueError, match="name"):
        safe_child(tmp_path, bad, ".json", PLAN_ID_RE, _refuse)


def test_safe_child_refuses_a_file_that_is_a_link_out_of_the_folder(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.json"
    outside.write_text("{}", encoding="utf-8")
    _link(outside, root / "plan_0123456789ab.json")
    with pytest.raises(ValueError, match="outside"):
        safe_child(root, "plan_0123456789ab", ".json", PLAN_ID_RE, _refuse)


def test_safe_child_refuses_a_resolved_file_outside_the_folder(tmp_path, monkeypatch):
    """Same refusal without needing symlink rights: pretend the OS resolved the file elsewhere."""
    from revit_mcp_server.security import safe_paths

    real = os.path.realpath
    elsewhere = real(tmp_path / "elsewhere" / "plan_0123456789ab.json")
    monkeypatch.setattr(safe_paths.os.path, "realpath", lambda p: elsewhere if str(p).endswith(".json") else real(p))
    with pytest.raises(ValueError, match="outside"):
        safe_child(tmp_path, "plan_0123456789ab", ".json", PLAN_ID_RE, _refuse)
    sibling = real(str(tmp_path) + "-sibling/plan_0123456789ab.json")
    monkeypatch.setattr(safe_paths.os.path, "realpath", lambda p: sibling if str(p).endswith(".json") else real(p))
    with pytest.raises(ValueError, match="outside"):
        safe_child(tmp_path, "plan_0123456789ab", ".json", PLAN_ID_RE, _refuse)


def test_safe_child_refuses_a_subfolder_that_is_a_link_out_of_the_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _link(elsewhere, root / ".claims")
    with pytest.raises(ValueError, match="outside"):
        safe_child(root, "plan_0123456789ab", "", PLAN_ID_RE, _refuse, subdir=".claims")


def test_snapshot_file_shape(tmp_path):
    assert snapshot_file(tmp_path, "01JABCDEFGHJKMNPQRSTVWXYZ0").name == "01JABCDEFGHJKMNPQRSTVWXYZ0.json"
    assert snapshot_file(tmp_path, "0123456789abcdef0123456789abcdef").name.endswith(".json")
    assert SNAPSHOT_ID_RE.fullmatch("snap1")
    for bad in SNAPSHOT_BAD:
        with pytest.raises(ValueError, match="plain snapshot name"):
            snapshot_file(tmp_path, bad)


# ---- plans: load / save / update / claim / lock / marker / in-flight / proof ----------


@pytest.fixture
def gate(tmp_path):
    return ApprovalGate(tmp_path, "required")


@pytest.mark.parametrize("bad", PLAN_BAD)
def test_every_plan_entry_point_refuses_a_hostile_plan_id(gate, tmp_path, bad):
    forged = {"plan_id": bad, "state": "approved", "actions": []}
    (tmp_path / "forged.json").write_text(json.dumps(forged, default=str), encoding="utf-8")
    with pytest.raises(BridgeError):
        gate.load_plan(bad)
    with pytest.raises(BridgeError):
        gate.save_plan(forged)
    with pytest.raises((BridgeError, ValueError)):
        gate.update_plan_state(bad, "approved", via="cli", expected_hash="sha256:0")
    with pytest.raises(BridgeError):
        with gate._plan_lock(bad):
            pass
    with pytest.raises(BridgeError):
        gate._claim_marker(bad, "act_0123456789ab")
    if isinstance(bad, str):
        with pytest.raises(BridgeError):
            gate.claim_action("revit_delete_element", {"element_id": 7, "plan_id": bad})
    # nothing was created next to or above the plans folder
    assert sorted(p.name for p in tmp_path.iterdir()) == ["forged.json", "plans"]
    assert not (gate.plans_dir / ".claims").exists() or not list((gate.plans_dir / ".claims").iterdir())


@pytest.mark.parametrize("bad", ["../x", "x/../y", "C:\\x", "\\\\s\\x", "", "x" * 81, "a b", "a.b", None, 5, "x\x00"])
def test_inflight_request_id_cannot_name_another_file(gate, bad):
    with pytest.raises(BridgeError):
        gate._inflight_path(bad)
    assert gate.in_flight(bad) is None


@pytest.mark.parametrize("bad", ["plan_0123456789ab", "x", "", None, 5, "../x", "ACT_0123456789AB",
                                 "act_0123456789ab/../x", "act_0123456789a\u0430"])
def test_claim_marker_needs_a_real_action_id(gate, bad):
    with pytest.raises(BridgeError, match="malformed action id"):
        gate._claim_marker(VALID_PLAN, bad)


def test_valid_plan_and_action_ids_still_work(gate):
    created = gate.create_plan([{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "P", "value": "1"}}], [{}])
    pid = created["plan_id"]
    assert PLAN_ID_RE.fullmatch(pid)
    assert gate.load_plan(pid)["plan_id"] == pid
    assert gate._get_plan_path(pid) == Path(os.path.realpath(gate.plans_dir)) / f"{pid}.json"
    gate.update_plan_state(pid, "approved", via="cli", expected_hash=plan_hash(gate.load_plan(pid)))
    claim = gate.claim_action(SET, {"element_id": 1, "parameter_name": "P", "value": "1", "plan_id": pid})
    marker = gate._claim_marker(pid, claim["action_id"])
    assert marker.is_file() and marker.parent == Path(os.path.realpath(gate.plans_dir)) / ".claims"
    assert gate.mark_in_flight(claim, "req-1", SET) is True
    assert gate.in_flight("req-1")["plan_id"] == pid


def test_a_plan_file_that_is_a_link_out_of_the_plans_folder_is_refused(gate, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"plan_id": VALID_PLAN, "state": "approved", "actions": []}), encoding="utf-8")
    _link(outside, gate.plans_dir / f"{VALID_PLAN}.json")
    with pytest.raises(BridgeError, match="outside the plans folder"):
        gate.load_plan(VALID_PLAN)


def test_a_claims_folder_that_is_a_link_out_of_the_plans_folder_is_refused(gate, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _link(elsewhere, gate.plans_dir / ".claims")
    with pytest.raises(BridgeError):
        gate._claim_marker(VALID_PLAN, "act_0123456789ab")
    assert list(elsewhere.iterdir()) == []


PROOF_BAD = TRAVERSAL + ["a" * 129]


@pytest.mark.parametrize("bad", PROOF_BAD)
def test_proof_entry_points_refuse_hostile_ids(tmp_path, bad):
    with pytest.raises(ValueError, match="Invalid plan_id"):
        proof_mod.proof_path(tmp_path, bad)
    with pytest.raises(ValueError, match="Invalid plan_id"):
        proof_mod.read_proof(tmp_path, bad)
    with pytest.raises(ValueError, match="Invalid plan_id"):
        proof_mod.write_proof(tmp_path, {"plan_id": bad})
    assert list(tmp_path.iterdir()) == []


def test_proof_valid_id_round_trips_and_a_link_is_refused(tmp_path):
    proof_mod.write_proof(tmp_path, {"plan_id": VALID_PLAN, "outcome": "success"})
    assert proof_mod.read_proof(tmp_path, VALID_PLAN)["outcome"] == "success"
    assert proof_mod.proof_path(tmp_path, VALID_PLAN) == Path(os.path.realpath(tmp_path)) / "proofs" / f"{VALID_PLAN}.json"
    other = "plan_ffffffffffff"
    outside = tmp_path / "outside.json"
    outside.write_text('{"outcome": "forged"}', encoding="utf-8")
    _link(outside, tmp_path / "proofs" / f"{other}.json")
    with pytest.raises(ValueError, match="Invalid plan_id"):
        proof_mod.read_proof(tmp_path, other)


def test_proof_folder_that_is_a_link_is_refused(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _link(elsewhere, work / "proofs")
    with pytest.raises(ValueError, match="Invalid plan_id"):
        proof_mod.write_proof(work, {"plan_id": VALID_PLAN})
    assert list(elsewhere.iterdir()) == []


# ---- recipes: load / save / delete / standing --------------------------------------


@pytest.mark.parametrize("bad", RECIPE_BAD)
def test_every_recipe_store_entry_point_refuses_a_hostile_id(tmp_path, bad):
    store = RecipeStore(tmp_path, starter_dir=tmp_path / "starters")
    for call in (
        lambda: store.load(bad),
        lambda: store.save(bad, code=READ_CODE, title="t", description="", params=None, mode="read"),
        lambda: store.delete(bad),
        lambda: store._file(store.dir, bad, ".json"),
        lambda: store._standing_file(bad),
    ):
        with pytest.raises(RecipeError) as err:
            call()
        assert err.value.kind == "invalid_id"
    with pytest.raises(RecipeError):
        store.grant_standing(bad, "0" * 64, "me")
    assert store.standing_record(bad) is None
    assert store.revoke_standing(bad) is False
    assert list(tmp_path.iterdir()) == []


def test_recipe_valid_ids_still_work(tmp_path):
    store = RecipeStore(tmp_path)
    store.save("my-recipe_1", code=READ_CODE, title="t", description="", params=None, mode="read")
    assert store.load("my-recipe_1").id == "my-recipe_1"
    assert store._file(store.dir, "my-recipe_1", ".py").parent == Path(os.path.realpath(store.dir))
    assert store.delete("my-recipe_1") is True
    assert ID_RE.fullmatch("a") and ID_RE.fullmatch("a" * 64)


def test_recipe_file_that_is_a_link_out_of_the_folder_is_refused(tmp_path):
    store = RecipeStore(tmp_path)
    store.dir.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text(READ_CODE, encoding="utf-8")
    _link(outside, store.dir / "evil.py")
    with pytest.raises(RecipeError) as err:
        store.load("evil")
    assert err.value.kind == "invalid_id"
    with pytest.raises(RecipeError):
        store.save("evil", code="# changed\n", title="t", description="", params=None, mode="read")
    assert outside.read_text(encoding="utf-8") == READ_CODE


# ---- snapshot ids in the report and QA modules ---------------------------------------


def _load_module(relpath: str, name: str):
    path = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Workspace:
    def __init__(self, root: Path):
        self.allowed_directories = [root]


@pytest.fixture
def snapshot_workspace(tmp_path):
    work = tmp_path / "work"
    (work / "snapshots").mkdir(parents=True)
    (tmp_path / "x.json").write_text(json.dumps({"elements": [], "types": [], "source": {}}), encoding="utf-8")
    return _Workspace(work)


SNAPSHOT_ATTACKS = ["../x", "..\\x", "../../x", "/etc/passwd", "C:\\x", "\\\\s\\share\\x", "x\x00", "a/b", "x" * 65]


@pytest.mark.parametrize("bad", SNAPSHOT_ATTACKS)
def test_report_generator_refuses_a_hostile_snapshot_id(snapshot_workspace, bad):
    rg = _load_module("src/revit_mcp_server/modules/report_generator/module.py", "_rg_safe")
    module = rg.ReportGeneratorModule()
    with pytest.raises(ValueError, match="plain snapshot name"):
        rg._get_data(bad, snapshot_workspace)
    with pytest.raises(ValueError, match="plain snapshot name"):
        rg._load_source(bad, snapshot_workspace)
    with pytest.raises(ValueError, match="plain snapshot name"):
        rg._load_review_snapshot(bad, snapshot_workspace)
    for call in (module.export_excel, module.build_review_pack, module.export_sqlite_summary):
        with pytest.raises(ValueError, match="plain snapshot name"):
            call(snapshot_id=bad, workspace=snapshot_workspace)


@pytest.mark.parametrize("bad", SNAPSHOT_ATTACKS)
def test_qaqc_checker_refuses_a_hostile_snapshot_id(snapshot_workspace, bad):
    qa = _load_module("src/revit_mcp_server/modules/qaqc_checker/module.py", "_qa_safe")
    module = qa.QaqcCheckerModule()
    with pytest.raises(ValueError, match="plain snapshot name"):
        module._get_data(bad, snapshot_workspace)
    with pytest.raises(ValueError, match="plain snapshot name"):
        module.run_check(snapshot_id=bad, workspace=snapshot_workspace)


def test_valid_snapshot_ids_still_load(snapshot_workspace):
    rg = _load_module("src/revit_mcp_server/modules/report_generator/module.py", "_rg_safe_ok")
    qa = _load_module("src/revit_mcp_server/modules/qaqc_checker/module.py", "_qa_safe_ok")
    payload = {"snapshot_id": "snap1", "elements": [{"uid": "u1"}], "types": [], "source": {"doc_guid": "g"}}
    (snapshot_workspace.allowed_directories[0] / "snapshots" / "snap1.json").write_text(json.dumps(payload), encoding="utf-8")
    assert rg._get_data("snap1", snapshot_workspace)[0] == [{"uid": "u1"}]
    assert rg._load_source("snap1", snapshot_workspace) == {"doc_guid": "g"}
    assert rg._load_review_snapshot("snap1", snapshot_workspace)["snapshot_id"] == "snap1"
    assert qa.QaqcCheckerModule()._get_data("snap1", snapshot_workspace)[0] == [{"uid": "u1"}]
    with pytest.raises(ValueError, match="not found"):
        rg._get_data("missing", snapshot_workspace)
    with pytest.raises(ValueError, match="not found"):
        qa.QaqcCheckerModule()._get_data("missing", snapshot_workspace)


# ---- workspace sandbox ---------------------------------------------------------------


def test_workspace_accepts_inside_and_refuses_outside_and_reserved(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    monitor = WorkspaceMonitor([work])
    assert monitor.assert_in_workspace(work / "a.txt") == Path(os.path.realpath(work)) / "a.txt"
    assert monitor.assert_in_workspace(work) == Path(os.path.realpath(work))
    for bad in (work / ".." / "x.txt", tmp_path / "other.txt", Path("C:/Windows/x") if os.name == "nt" else Path("/etc/x"),
                work.parent / (work.name + "-sibling") / "x"):
        with pytest.raises(WorkspaceViolation, match="outside"):
            monitor.assert_in_workspace(bad)
    for reserved in (work / "plans" / "plan_0123456789ab.json", work / "proofs", work / "plans" / ".claims" / "x",
                     work / "x" / ".." / "plans" / "y"):
        with pytest.raises(WorkspaceViolation, match="reserved"):
            monitor.assert_in_workspace(reserved)
    assert is_reserved_path(work / "plans", work) and not is_reserved_path(work / "plans2", work)


def test_workspace_ignores_case_when_casefold_is_on(tmp_path):
    """Runs on every OS: the flag forces the Windows rule."""
    work = tmp_path / "Work"
    work.mkdir()
    monitor = WorkspaceMonitor([work], casefold=True)
    monitor.assert_in_workspace(Path(str(work).upper()) / "a.txt")
    with pytest.raises(WorkspaceViolation, match="reserved"):
        monitor.assert_in_workspace(Path(str(work).upper()) / "PLANS" / "a.json")
    assert is_reserved_path(Path(str(work).upper()) / "Proofs", work, casefold=True)


def test_workspace_is_case_sensitive_when_casefold_is_off(tmp_path):
    work = tmp_path / "Work"
    work.mkdir()
    monitor = WorkspaceMonitor([work], casefold=False)
    with pytest.raises(WorkspaceViolation, match="outside the allowed workspace"):
        monitor.assert_in_workspace(Path(str(work).upper()) / "a.txt")
    monitor.assert_in_workspace(work / "PLANS" / "a.json")  # a different folder name, not reserved
    assert not is_reserved_path(work / "PLANS", work, casefold=False)


def test_default_casefold_follows_the_os(tmp_path):
    work = tmp_path / "Work"
    work.mkdir()
    monitor = WorkspaceMonitor([work])
    other_case = Path(str(work).upper()) / "a.txt"
    if os.name == "nt":
        monitor.assert_in_workspace(other_case)
    else:
        with pytest.raises(WorkspaceViolation, match="outside the allowed workspace"):
            monitor.assert_in_workspace(other_case)


def test_safe_child_tells_the_caller_why_it_refused(tmp_path):
    """The reason picks the message (approval._refuse_plan_id says 'outside the plans folder')."""
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.json").write_text("{}")
    _link(tmp_path / "secret.json", root / "out.json")
    (root / "sub").mkdir()
    (root / "sub" / "inner.json").write_text("{}")
    _link(root / "sub" / "inner.json", root / "deep.json")  # under the root, but not a direct child
    reasons = []

    def refuse(reason):
        reasons.append(reason)
        return RuntimeError(reason)

    for name in ("../x", "out", "deep"):
        with pytest.raises(RuntimeError):
            safe_child(root, name, ".json", SNAPSHOT_ID_RE, refuse)
    assert reasons == ["name", "outside", "outside"]


@pytest.mark.parametrize("bad", ["\x00", "a\x00b.txt", "plans\x00", "..\x00/x"])
def test_workspace_refuses_a_nul_path_with_workspace_violation(tmp_path, bad):
    """Regression (#296, found by the property tests): a NUL raised a bare ValueError from the OS layer,
    so callers that catch WorkspaceViolation reported an execution error instead of a sandbox refusal."""
    work = tmp_path / "work"
    work.mkdir()
    monitor = WorkspaceMonitor([work])
    with pytest.raises(WorkspaceViolation, match="NUL"):
        monitor.assert_in_workspace(work / bad)
    with pytest.raises(WorkspaceViolation, match="NUL"):
        monitor.assert_in_workspace(Path(bad))
    with pytest.raises(WorkspaceViolation, match="NUL"):
        is_reserved_path(work / bad, work)


def test_workspace_refuses_a_link_that_leaves_the_workspace(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _link(elsewhere, work / "link")
    with pytest.raises(WorkspaceViolation, match="outside"):
        WorkspaceMonitor([work]).assert_in_workspace(work / "link" / "secret.txt")
