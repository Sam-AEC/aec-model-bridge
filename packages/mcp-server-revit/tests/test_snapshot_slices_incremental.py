"""Sliced and incremental snapshots (issues 289, 290), server side.

FakeAddin follows the rules of the C# revit.extract_snapshot: slice sessions with cursors, a
per-document change journal (epoch + sequence number), incremental captures that re-read changed
elements and instances of changed types and list every UniqueId in scope. It runs no Revit; the
add-in half is guarded separately and is UNVERIFIED live.
"""
import asyncio
import copy
import json
import uuid
from types import SimpleNamespace

import pytest

from revit_mcp_server.providers.revit import _snapshot_payload
from revit_mcp_server.providers.semantic_provider import SemanticProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.semantic import engine


class FakeAddin:
    def __init__(self, folder, doc_guid="doc-1"):
        self.dir = folder / "addin" / "snapshots"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.doc_guid = doc_guid
        self.types = {"10": {"family": "Single-Flush", "name": "0915 x 2134mm"},
                      "11": {"family": "Basic Wall", "name": "Generic 200"}}
        self.elements = []  # ordered like a collector
        for i in range(25):
            door = i % 2 == 0
            self.elements.append({
                "uid": f"uid-{i:03d}", "element_id": 100 + i,
                "category": "OST_Doors" if door else "OST_Walls",
                "class": "FamilyInstance" if door else "Wall",
                "type_id": "10" if door else "11",
                "params": {"Mark": f"M-{i}", "Comments": "", "Fire Rating": "60" if door else "",
                           "Width": 0.9 if door else 0.2},
            })
        self.views = [{"uid": "view-1", "name": "Level 1", "type": "FloorPlan"}]
        self.sheets = [{"uid": "sheet-1", "number": "A-101", "views": ["view-1"]}]
        self.epoch, self.seq, self.changed_at = uuid.uuid4().hex, 0, {}
        self.sessions = {}
        self.calls = []

    # --- model edits (what DocumentChanged would report) -------------------------------------
    def _touch(self, *uids):
        self.seq += 1
        for uid in uids:
            self.changed_at[uid] = self.seq

    def modify(self, uid, **params):
        el = next(e for e in self.elements if e["uid"] == uid)
        el["params"].update(params)
        self._touch(uid)

    def add(self, uid, after_index):
        el = {"uid": uid, "element_id": 900, "category": "OST_Doors", "class": "FamilyInstance",
              "type_id": "10", "params": {"Mark": "NEW", "Comments": "", "Fire Rating": "30", "Width": 0.8}}
        self.elements.insert(after_index, el)
        self._touch(uid)

    def delete(self, uid):
        self.elements = [e for e in self.elements if e["uid"] != uid]
        self.seq += 1  # deletions advance the journal but need no entry

    def rename_type(self, type_id, name):
        self.types[type_id]["name"] = name
        self._touch(f"type-{type_id}")  # the type element is modified, its instances are not

    def reopen(self):
        self.epoch, self.seq, self.changed_at = uuid.uuid4().hex, 0, {}

    # --- extraction -------------------------------------------------------------------------
    def _scope(self, payload):
        cats = {engine._category_key(c) for c in payload.get("categories") or []}
        return [e for e in self.elements if not cats or engine._category_key(e["category"]) in cats]

    def _record(self, el, params):
        t = self.types[el["type_id"]]
        values = el["params"] if params is None else {k: v for k, v in el["params"].items() if k in params}
        return {
            "uid": el["uid"], "amb_uid": el["uid"], "element_id": el["element_id"], "category": el["category"],
            "class": el["class"], "name": t["name"], "sheet_number": None, "type_uid": el["type_id"],
            "family": t["family"], "type_name": t["name"], "level_uid": "5", "location": None, "host_uid": None,
            "params": {k: {"v": v, "storage": "String" if isinstance(v, str) else "Double",
                           "instance": True, "readonly": False} for k, v in values.items()},
        }

    def _counts(self, payload, scope, captured, truncated=False):
        counts = {"candidates": len(scope), "captured": captured, "truncated": truncated, "dirty_only": False,
                  "categories": ["OST_" + engine._category_key(c).title() for c in payload.get("categories") or []],
                  "tracker": {"epoch": self.epoch, "seq": self.seq}}
        if payload.get("params"):
            counts["params"] = list(payload["params"])
        return counts

    def _write(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def _doc(self, sid, elements, counts, whole):
        return {"schema": "amb.snapshot/1", "snapshot_id": sid, "taken_at": "2026-11-24T10:00:00Z",
                "source": {"app": "revit", "doc_guid": self.doc_guid, "doc_title": "Model.rvt", "units": "SI"},
                "elements": elements, "views": copy.deepcopy(self.views) if whole else None,
                "sheets": copy.deepcopy(self.sheets) if whole else None, "dirty_only": False,
                "counts": counts, "deleted": []}

    async def execute_tool(self, name, payload):
        assert name == "revit_extract_snapshot"
        self.calls.append(dict(payload))
        if payload.get("cursor"):
            return self._continue(payload["cursor"])
        scope = self._scope(payload)
        whole = not payload.get("categories")
        params = payload.get("params")
        sid = uuid.uuid4().hex
        reason, reread = None, None
        if payload.get("base_epoch") is not None:
            if payload["base_epoch"] != self.epoch or not 0 <= payload["base_seq"] <= self.seq:
                reason = "The change journal of this document does not cover the base snapshot; a full snapshot was taken."
            else:
                changed = {u for u, s in self.changed_at.items() if s > payload["base_seq"]}
                changed_types = {u[5:] for u in changed if u.startswith("type-")}
                reread = [e for e in scope if e["uid"] in changed or e["type_id"] in changed_types]
        if reread is not None:
            counts = self._counts(payload, reread, len(reread))
            counts["incremental"] = True
            data = self._doc(sid, [self._record(e, params) for e in reread], counts, whole)
            data["incremental"] = True
            data["current_uids"] = [e["uid"] for e in scope]
            return {"snapshot_id": sid, "path": self._write(f"{sid}.delta.json", data), "incremental": True}
        if payload.get("slice_size"):
            session = {"id": uuid.uuid4().hex, "sid": sid, "scope": scope, "params": params, "payload": payload,
                       "size": payload["slice_size"], "whole": whole, "seq": self.seq, "epoch": self.epoch,
                       "reason": reason}
            self.sessions[session["id"]] = session
            if whole:  # first call: views and sheets only
                counts = self._counts(payload, scope, 0)
                counts["views_in_scope"] = True
                data = self._doc(sid, [], counts, True)
                data["part"] = {"offset": 0, "next_offset": 0, "first": True}
                return self._slice_result(session, self._write(f"{sid}.part-start.json", data), 0, 0)
            return self._slice(session, 0, first=True)
        records = [self._record(e, params) for e in scope]
        counts = self._counts(payload, scope, len(records))
        if reason:
            counts["incremental"] = False
            counts["incremental_reason"] = reason
        data = self._doc(sid, records, counts, whole)
        return {"snapshot_id": sid, "path": self._write(f"{sid}.json", data),
                "incremental": False, "incremental_reason": reason}

    def _continue(self, cursor):
        sid, offset = cursor.rsplit(":", 1)
        return self._slice(self.sessions[sid], int(offset), first=False)

    def _slice(self, session, offset, first):
        nxt = min(offset + session["size"], len(session["scope"]))
        records = [self._record(e, session["params"]) for e in session["scope"][offset:nxt]]
        counts = self._counts(session["payload"], session["scope"], 0)
        counts["tracker"] = {"epoch": session["epoch"], "seq": session["seq"]}
        counts["views_in_scope"] = False
        data = self._doc(session["sid"], records, counts, False)
        data["part"] = {"offset": offset, "next_offset": nxt, "first": first}
        return self._slice_result(session, self._write(f"{session['sid']}.part-{offset:07d}.json", data), offset, nxt)

    def _slice_result(self, session, path, offset, nxt):
        done = nxt >= len(session["scope"])
        return {"snapshot_id": session["sid"], "path": path, "sliced": True, "slice_offset": offset,
                "next_offset": nxt, "next_cursor": None if done else f"{session['id']}:{nxt}",
                "changed_during_capture": self.seq != session["seq"], "incremental": False,
                "incremental_reason": session["reason"]}


@pytest.fixture
def live(monkeypatch):
    from revit_mcp_server.config import BridgeMode, config

    monkeypatch.setattr(config, "mode", BridgeMode.bridge)


def _take(ws, addin, **options):
    return asyncio.run(engine.snapshot_take(ws, addin, options))


def _saved(tmp_path, sid):
    return json.loads((tmp_path / "snapshots" / f"{sid}.json").read_text(encoding="utf-8"))


def _content(data):
    """The model content of a snapshot: everything except identity, timing and coverage metadata."""
    return {k: v for k, v in data.items() if k not in ("snapshot_id", "taken_at", "counts")}


# --- slices ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("categories", [None, ["Doors"]])
def test_sliced_capture_equals_single_call_capture(tmp_path, live, categories):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    scope = {"categories": categories} if categories else {}
    full = _take(ws, addin, **scope)
    sliced = _take(ws, addin, slice_size=10, **scope)
    a, b = _saved(tmp_path, full.snapshot_id), _saved(tmp_path, sliced.snapshot_id)
    assert _content(a) == _content(b)
    assert b["counts"]["sliced"] is True and b["counts"]["truncated"] is False
    assert b["counts"]["captured"] == len(a["elements"])
    assert "views_in_scope" not in b["counts"]
    expected_calls = -(-len(a["elements"]) // 10) + (0 if categories else 1)
    assert b["counts"]["slices"] == expected_calls
    assert [c.get("cursor") is not None for c in addin.calls[1:]] == [False] + [True] * (expected_calls - 1)
    # Part files are merged and removed; only the single-call file stays in the add-in folder.
    assert sorted(p.name for p in addin.dir.iterdir()) == [f"{full.snapshot_id}.json"]


def test_sliced_capture_stopped_by_total_time_is_marked_truncated(tmp_path, live, monkeypatch):
    monkeypatch.setattr(engine, "SLICED_MAX_TOTAL_SECONDS", -1.0)
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    snap = _take(ws, addin, slice_size=10, categories=["Doors"])
    assert snap.counts["truncated"] is True and len(snap.elements) == 10


def test_slice_that_makes_no_progress_is_refused(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    original = addin._slice

    def stuck(session, offset, first):
        res = original(session, offset, first)
        if not first:
            res["next_cursor"] = f"{session['id']}:{offset}"
            path = res["path"]
            data = json.loads(open(path, encoding="utf-8").read())
            data["part"]["next_offset"] = offset
            open(path, "w", encoding="utf-8").write(json.dumps(data))
        return res

    addin._slice = stuck
    with pytest.raises(RuntimeError, match="no progress"):
        _take(ws, addin, slice_size=10, categories=["Doors"])


def test_slice_reply_that_is_not_a_slice_is_refused(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    original = addin._continue
    addin._continue = lambda cursor: {"status": "running", "request_id": "r1"} if cursor else original(cursor)
    with pytest.raises(RuntimeError, match="did not come back as a slice"):
        _take(ws, addin, slice_size=10, categories=["Doors"])


def test_changes_between_slices_are_reported(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    original = addin._continue

    def edit_then_continue(cursor):
        addin.modify("uid-000", Mark="EDITED")
        return original(cursor)

    addin._continue = edit_then_continue
    registry = SimpleNamespace(get_provider=lambda name: addin if name == "revit" else None)
    result = asyncio.run(SemanticProvider(ws, registry)._snapshot_take({"slice_size": 10, "categories": ["Doors"]}))
    assert result["changed_during_capture"] is True and "mixes states" in result["note"]
    assert result["slices"] == 2


# --- params -------------------------------------------------------------------------------------

def test_params_are_sent_validated_and_mark_the_snapshot_partial(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    snap = _take(ws, addin, params=[" Mark ", "Fire Rating", "Mark"])
    assert addin.calls[0]["params"] == ["Mark", "Fire Rating"]
    assert all(set(el.params) <= {"Mark", "Fire Rating"} for el in snap.elements)
    assert snap.counts["params"] == ["Mark", "Fire Rating"]

    from revit_mcp_server.modules.qa_handover.module import _is_partial
    from revit_mcp_server.modules.report_generator.module import _is_partial_snapshot

    data = _saved(tmp_path, snap.snapshot_id)
    assert _is_partial(data) and _is_partial_snapshot(data)


@pytest.mark.parametrize("bad, message", [
    ("Mark", "list"), ([1], "strings"), ([" "], "empty"), (["x" * 201], "at most"),
    ([f"p{i}" for i in range(101)], "at most 100"), ([], "at least one"),
])
def test_malformed_params_are_refused_before_revit_is_called(tmp_path, live, bad, message):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    with pytest.raises(ValueError, match=message):
        _take(ws, addin, params=bad)
    assert addin.calls == []


@pytest.mark.parametrize("bad", [0, 9, 5001, True, "200"])
def test_slice_size_out_of_range_is_refused(tmp_path, live, bad):
    with pytest.raises(ValueError, match="slice_size"):
        _take(WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path), slice_size=bad)


def test_params_in_mock_mode_project_the_mock_snapshot(tmp_path):
    snap = asyncio.run(engine.snapshot_take(WorkspaceMonitor([tmp_path]), None, {"params": ["Mark"]}))
    assert snap.counts["params"] == ["Mark"]
    assert all(set(el.params) <= {"Mark"} for el in snap.elements)
    assert any(el.params for el in snap.elements)


def test_revit_provider_forwards_snapshot_options_to_the_addin():
    payload = _snapshot_payload({"categories": ["Doors"], "max_elements": 10, "params": ["Mark"], "slice_size": 50,
                                 "cursor": "abc:10", "base_epoch": "e", "base_seq": 3, "ignored": 1})
    assert payload == {"dirty_only": False, "categories": ["Doors"], "max_elements": 10, "params": ["Mark"],
                       "slice_size": 50, "cursor": "abc:10", "base_epoch": "e", "base_seq": 3}
    assert _snapshot_payload({}) == {"dirty_only": False}


# --- incremental --------------------------------------------------------------------------------

def _edit_model(addin):
    addin.modify("uid-003", Comments="checked")
    addin.add("uid-new", 5)
    addin.delete("uid-010")
    addin.rename_type("10", "0915 x 2100mm")


@pytest.mark.parametrize("scope", [{}, {"categories": ["Doors"]}, {"params": ["Mark", "Comments"]}])
def test_incremental_merge_equals_full_capture_of_the_changed_model(tmp_path, live, scope):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin, **scope)
    _edit_model(addin)
    merged = _take(ws, addin, base_snapshot_id=base.snapshot_id, **scope)
    full = _take(ws, addin, **scope)
    m, f = _saved(tmp_path, merged.snapshot_id), _saved(tmp_path, full.snapshot_id)
    assert _content(m) == _content(f)
    assert m["counts"]["incremental"] is True and m["counts"]["base_snapshot_id"] == base.snapshot_id
    assert m["counts"]["captured"] == m["counts"]["candidates"] == len(f["elements"])
    changes = m["counts"]["incremental_changes"]
    assert changes["deleted"] == 1 and changes["added"] == 1
    # Re-read: every door (the door type was renamed; the new door is one of them), plus uid-003,
    # a wall, when walls are in scope.
    doors = sum(1 for e in addin.elements if e["type_id"] == "10")
    assert changes["reread"] == doors + (0 if scope.get("categories") == ["Doors"] else 1)
    assert "current_uids" not in m and "incremental" not in m
    assert not list(addin.dir.glob("*.delta.json"))
    assert "base_epoch" in addin.calls[1] and addin.calls[1]["base_seq"] == base.counts["tracker"]["seq"]


def test_incremental_rereads_only_changed_elements_and_instances_of_changed_types(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin)
    addin.modify("uid-001", Comments="wall checked")
    merged = _take(ws, addin, base_snapshot_id=base.snapshot_id)
    assert merged.counts["incremental_changes"] == {"reread": 1, "added": 0, "modified": 1, "deleted": 0}
    addin.rename_type("11", "Generic 250")
    merged2 = _take(ws, addin, base_snapshot_id=merged.snapshot_id)
    walls = sum(1 for e in addin.elements if e["type_id"] == "11")
    assert merged2.counts["incremental_changes"]["reread"] == walls
    assert {el.type_name for el in merged2.elements if el.category == "OST_Walls"} == {"Generic 250"}


def test_incremental_chain_stays_equal_to_full_capture(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    current = _take(ws, addin)
    for step in range(3):
        addin.modify(f"uid-{step:03d}", Mark=f"R{step}")
        addin.delete(f"uid-{20 + step:03d}")
        current = _take(ws, addin, base_snapshot_id=current.snapshot_id)
        assert current.counts["incremental"] is True
    full = _take(ws, addin)
    assert _content(_saved(tmp_path, current.snapshot_id)) == _content(_saved(tmp_path, full.snapshot_id))


def test_no_changes_gives_an_equal_snapshot(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin)
    merged = _take(ws, addin, base_snapshot_id=base.snapshot_id)
    assert merged.counts["incremental_changes"]["reread"] == 0
    assert _content(_saved(tmp_path, merged.snapshot_id)) == _content(_saved(tmp_path, base.snapshot_id))


def test_document_reopen_falls_back_to_a_full_capture_and_says_so(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin)
    addin.reopen()
    addin.modify("uid-002", Mark="X")
    registry = SimpleNamespace(get_provider=lambda name: addin if name == "revit" else None)
    result = asyncio.run(SemanticProvider(ws, registry)._snapshot_take({"base_snapshot_id": base.snapshot_id}))
    assert result["incremental"] is False and "change journal" in result["incremental_reason"]
    saved = _saved(tmp_path, result["snapshot_id"])
    assert saved["counts"]["incremental"] is False and len(saved["elements"]) == 25


def test_incremental_result_is_reported_by_the_provider(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    registry = SimpleNamespace(get_provider=lambda name: addin if name == "revit" else None)
    provider = SemanticProvider(ws, registry)
    base = asyncio.run(provider._snapshot_take({}))
    assert "incremental" not in base
    addin.modify("uid-004", Mark="Y")
    result = asyncio.run(provider._snapshot_take({"base_snapshot_id": base["snapshot_id"]}))
    assert result["incremental"] is True and result["incremental_changes"]["modified"] == 1
    assert result["elements_count"] == 25


@pytest.mark.parametrize("change, reason", [
    ({"counts": {"truncated": True}}, "partial capture"),
    ({"dirty_only": True}, "dirty-only"),
    ({"counts": {"tracker": None}}, "no change-journal position"),
    ({"schema": "other/1"}, "unknown schema"),
])
def test_unusable_base_gives_a_full_capture_without_asking_for_a_delta(tmp_path, live, change, reason):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin)
    data = _saved(tmp_path, base.snapshot_id)
    for key, value in change.items():
        if isinstance(value, dict):
            data[key].update(value)
        else:
            data[key] = value
    (tmp_path / "snapshots" / f"{base.snapshot_id}.json").write_text(json.dumps(data), encoding="utf-8")
    snap = _take(ws, addin, base_snapshot_id=base.snapshot_id)
    assert "base_epoch" not in addin.calls[-1]
    assert snap.counts["incremental"] is False and reason in snap.counts["incremental_reason"]
    assert len(snap.elements) == 25


@pytest.mark.parametrize("first, second, reason", [
    ({"categories": ["Doors"]}, {}, "different categories"),
    ({"params": ["Mark"]}, {"params": ["Comments"]}, "different params"),
])
def test_base_with_another_scope_gives_a_full_capture(tmp_path, live, first, second, reason):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin, **first)
    snap = _take(ws, addin, base_snapshot_id=base.snapshot_id, **second)
    assert snap.counts["incremental"] is False and reason in snap.counts["incremental_reason"]


def test_missing_base_is_refused(tmp_path, live):
    with pytest.raises(ValueError, match="not found"):
        _take(WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path), base_snapshot_id="nope")
    with pytest.raises(ValueError, match="plain snapshot name"):
        _take(WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path), base_snapshot_id="../x")


def test_unmergeable_delta_is_replaced_by_a_full_capture(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin)
    data = _saved(tmp_path, base.snapshot_id)
    data["elements"] = data["elements"][1:]  # the base lacks an element that did not change
    (tmp_path / "snapshots" / f"{base.snapshot_id}.json").write_text(json.dumps(data), encoding="utf-8")
    snap = _take(ws, addin, base_snapshot_id=base.snapshot_id)
    assert snap.counts["incremental"] is False and "could not be merged" in snap.counts["incremental_reason"]
    assert len(snap.elements) == 25 and len(addin.calls) == 3
    assert not list(addin.dir.glob("*.delta.json"))


def test_addin_without_incremental_support_gives_a_full_capture(tmp_path, live):
    ws, addin = WorkspaceMonitor([tmp_path]), FakeAddin(tmp_path)
    base = _take(ws, addin)
    original = addin.execute_tool

    async def old_addin(name, payload):
        payload = {k: v for k, v in payload.items() if k not in ("base_epoch", "base_seq")}
        res = await original(name, payload)
        res.pop("incremental", None)
        res.pop("incremental_reason", None)
        return res

    addin_old = SimpleNamespace(execute_tool=old_addin)
    snap = _take(ws, addin_old, base_snapshot_id=base.snapshot_id)
    assert snap.counts["incremental"] is False and "predate" in snap.counts["incremental_reason"]


def test_mock_mode_with_base_says_it_is_not_incremental(tmp_path):
    ws = WorkspaceMonitor([tmp_path])
    base = asyncio.run(engine.snapshot_take(ws, None, {}))
    snap = asyncio.run(engine.snapshot_take(ws, None, {"base_snapshot_id": base.snapshot_id}))
    assert snap.counts["incremental"] is False and "Mock mode" in snap.counts["incremental_reason"]


# --- merge_incremental directly -------------------------------------------------------------------

def _rec(uid, mark="A"):
    return {"uid": uid, "element_id": 1, "category": "OST_Doors", "class": "FamilyInstance",
            "params": {"Mark": {"v": mark, "storage": "String"}}}


def _base(*uids):
    return {"schema": "amb.snapshot/1", "snapshot_id": "b", "source": {"doc_guid": "d"},
            "elements": [_rec(u) for u in uids], "counts": {}}


def _delta(current, changed, **extra):
    data = {"schema": "amb.snapshot/1", "snapshot_id": "n", "source": {"doc_guid": "d"},
            "elements": changed, "counts": {"truncated": False}, "incremental": True, "current_uids": current}
    data.update(extra)
    return data


def test_merge_orders_by_current_uids_and_counts_changes():
    merged = engine.merge_incremental(_base("a", "b", "c"), _delta(["c", "x", "a"], [_rec("x"), _rec("a", "Z")]), "b")
    assert [e["uid"] for e in merged["elements"]] == ["c", "x", "a"]
    assert merged["elements"][2]["params"]["Mark"]["v"] == "Z"
    assert merged["counts"]["incremental_changes"] == {"reread": 2, "added": 1, "modified": 1, "deleted": 1}


@pytest.mark.parametrize("delta, message", [
    (_delta(["a", "q"], []), "neither in the base"),
    (_delta(["a"], [_rec("z")]), "not in the current element list"),
    (_delta(None, []), "no list"),
    (_delta(["a", "a"], []), "repeats"),
    (_delta(["a"], [], counts={"truncated": True}), "cut short"),
    (_delta(["a"], [], source={"doc_guid": "other"}), "another document"),
    (_delta(["a"], [{"element_id": 1}]), "no uid"),
])
def test_merge_refuses_inconsistent_input(delta, message):
    with pytest.raises(engine.IncrementalMergeError, match=message):
        engine.merge_incremental(_base("a"), delta, "b")


def test_part_files_are_removed_only_when_named_like_parts(tmp_path):
    folder = tmp_path / "snapshots"
    folder.mkdir()
    keep = [folder / "abc.json", folder / "other.part-0000000.json", tmp_path / "abc.part-0000000.json"]
    gone = folder / "abc.part-0000010.json"
    for p in keep + [gone]:
        p.write_text("{}", encoding="utf-8")
    for p in keep + [gone]:
        engine._discard_part_file(p, "abc")
    assert not gone.exists() and all(p.exists() for p in keep)
