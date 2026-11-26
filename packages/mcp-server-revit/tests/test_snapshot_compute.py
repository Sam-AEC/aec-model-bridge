"""snapshot_compute: read-only query pipelines over a saved snapshot."""

import asyncio
import json

import pytest

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.semantic_provider import SemanticProvider
from revit_mcp_server.semantic import engine
from revit_mcp_server.semantic import compute
from revit_mcp_server.semantic.compute import (
    MAX_LINKS, MAX_STEPS, QueryError, get_path, resolve_query, run_pipeline, validate_steps,
)
from revit_mcp_server.semantic.models import BBox, ElementRecord, ParamVal, TypeRecord


@pytest.fixture
def snap():
    snapshot = engine.generate_mock_snapshot()
    wall = next(e for e in snapshot.elements if e.category == "OST_Walls")
    wall.params["Fire Rating"] = ParamVal(v="60", storage="String")
    snapshot.elements.append(
        ElementRecord(
            uid="door-2", element_id=301, category="OST_Doors", cls="FamilyInstance",
            type_uid="door-type-uid-0001", family="Single-Flush", type_name="0915 x 2134mm",
            level_uid=wall.level_uid, host_uid=wall.uid,
            params={"Mark": ParamVal(v="D-102", storage="String"), "FireRating": ParamVal(v="60", storage="String")},
            room_uids={"4": "c0326e0e-473d-4952-b8ec-f23696541f46-room-placed"},
        )
    )
    snapshot.types[1] = TypeRecord(
        uid="door-type-uid-0001", category="OST_Doors", family="Single-Flush", type_name="0915 x 2134mm",
        params={"Width": ParamVal(v=0.915, storage="Double", instance=False)},
    )
    return snapshot


def test_parameter_paths_yield_values(snap):
    door = snap.elements[3].model_dump(by_alias=True, mode="json")
    assert get_path(door, "params.Mark") == "D-101"
    assert get_path(door, "location.xyz.0") == 5.0
    assert get_path(door, "params.Missing.v") is None
    assert get_path(door, "location.xyz.9") is None


def test_field_to_field_comparison_across_a_join(snap):
    """Doors whose fire rating is below their host wall's: one call instead of many."""
    out = run_pipeline(snap, [{
        "from": "elements",
        "join": ["host"],
        "where": [
            {"field": "category", "value": "OST_Doors"},
            {"field": "params.FireRating", "op": "lt", "value": {"field": "host.params.Fire Rating"}},
        ],
        "select": [{"field": "params.Mark", "as": "mark"}, {"field": "host.params.Fire Rating", "as": "wall"}],
    }])
    assert out["rows"] == [{"mark": "D-101", "wall": "60"}]
    assert out["row_count"] == 1 and not out["truncated"]


def test_steps_chain_group_and_aggregate(snap):
    out = run_pipeline(snap, [
        {"name": "doors", "where": {"field": "category", "value": "OST_Doors"}, "join": ["type", "level"]},
        {
            "name": "by_level", "from": "$doors", "group_by": ["level.type_name"],
            "aggregate": {"n": "count", "marks": {"op": "list", "field": "params.Mark"},
                          "width": {"op": "max", "field": "type.params.Width"}},
        },
    ])
    assert out["returned_step"] == "by_level"
    assert out["rows"] == [{"level.type_name": "Level 1", "n": 2, "marks": ["D-101", "D-102"], "width": 0.915}]
    assert out["step_counts"] == {"doors": 2, "by_level": 1}


def test_projected_dotted_path_can_be_filtered(snap):
    out = run_pipeline(snap, [
        {"name": "doors", "where": {"field": "category", "value": "OST_Doors"}, "select": ["params.Mark"]},
        {"name": "one", "from": "$doors", "where": {"field": "params.Mark", "value": "D-102"}},
    ])
    assert out["rows"] == [{"params.Mark": "D-102"}]


def test_grouped_dotted_key_can_be_selected(snap):
    out = run_pipeline(snap, [
        {"name": "doors", "where": {"field": "category", "value": "OST_Doors"},
         "group_by": ["params.Mark"], "aggregate": {"n": "count"}},
        {"name": "marks", "from": "$doors", "select": ["params.Mark", "n"], "sort": [{"field": "params.Mark"}]},
    ])
    assert out["rows"] == [{"params.Mark": "D-101", "n": 1}, {"params.Mark": "D-102", "n": 1}]


def test_return_an_earlier_step_and_sort_desc(snap):
    out = run_pipeline(snap, [
        {"name": "rooms", "where": {"field": "category", "value": "OST_Rooms"},
         "sort": [{"field": "params.Area", "desc": True}], "select": ["params.Number"]},
        {"name": "total", "from": "$rooms", "aggregate": {"n": "count"}},
    ], return_step="rooms")
    assert out["rows"] == [{"params.Number": "102"}, {"params.Number": "101"}]


def test_any_not_in_and_text_ops(snap):
    out = run_pipeline(snap, [{
        "where": {"all": [
            {"any": [{"field": "category", "op": "in", "value": ["OST_Doors", "OST_Walls"]}]},
            {"not": {"field": "family", "op": "startswith", "value": "basic", "ci": True}},
            {"field": "params.Mark", "op": "exists"},
        ]},
        "select": ["params.Mark"],
        "sort": "params.Mark",
    }])
    assert [r["params.Mark"] for r in out["rows"]] == ["D-101", "D-102"]


def test_room_and_hosted_and_relation_joins(snap):
    out = run_pipeline(snap, [
        {"name": "walls", "where": {"field": "category", "value": "OST_Walls"},
         "join": ["hosted", {"rel": "relation_out", "kind": "hosts", "as": "hosts"}],
         "select": [{"field": "hosted.1.params.Mark", "as": "second"}, {"field": "hosts.0.params.Mark", "as": "rel"}]},
        {"name": "rooms", "where": {"field": "uid", "value": "door-2"}, "join": ["room"],
         "select": [{"field": "room.params.Number", "as": "room"}]},
    ], return_step="walls")
    assert out["rows"] == [{"second": "D-102", "rel": "D-101"}]
    assert run_pipeline(snap, [{"where": {"field": "uid", "value": "door-2"}, "join": ["room"],
                                "select": ["room.params.Number"]}])["rows"] == [{"room.params.Number": "102"}]


def test_max_rows_truncates_but_counts_all(snap):
    out = run_pipeline(snap, [{"select": ["uid"]}], max_rows=2)
    assert len(out["rows"]) == 2 and out["truncated"] and out["row_count"] == len(snap.elements)


def test_numbers_compare_as_numbers_and_mismatches_do_not_match(snap):
    rows = run_pipeline(snap, [{"where": {"field": "params.Area", "op": "gte", "value": "10"}, "select": ["uid"]}])["rows"]
    assert len(rows) == 1
    assert run_pipeline(snap, [{"where": {"field": "params.Mark", "op": "gt", "value": 3}}])["rows"] == []


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([], "non-empty"),
        ([{"from": "elements"}] * (MAX_STEPS + 1), "at most"),
        ([{"from": "/etc/passwd"}], "'from'"),
        ([{"from": "$later"}, {"name": "later"}], "'from'"),
        ([{"where": {"field": "x", "op": "regex", "value": "a+"}}], "unknown op"),
        ([{"where": {"field": "x", "op": "eq"}}], "needs a value"),
        ([{"where": {"field": "x", "value": {"code": "1"}}}], "object value"),
        ([{"where": {"field": "x", "value": 1, "eval": "1"}}], "unknown where keys"),
        ([{"join": ["sql"]}], "unknown join"),
        ([{"aggregate": {"n": {"op": "median", "field": "x"}}}], "unknown aggregate"),
        ([{"lambda": "x"}], "unknown keys"),
        ([{"name": "a"}, {"name": "a"}], "new name"),
        ([{"name": "elements"}], "new name"),
        ([{"sort": [3]}], "sort items"),
        ([{"limit": -1}], "limit"),
        ([{"where": {"not": {"not": {"not": {"not": {"not": {"not": {"not": {"field": "x", "op": "exists"}}}}}}}}}], "deeper"),
    ],
)
def test_malformed_pipelines_are_refused(snap, steps, message):
    with pytest.raises(QueryError, match=message):
        run_pipeline(snap, steps)


def test_bad_return_and_max_rows(snap):
    with pytest.raises(QueryError, match="return"):
        run_pipeline(snap, [{"name": "a"}], return_step="b")
    with pytest.raises(QueryError, match="max_rows"):
        run_pipeline(snap, [{"name": "a"}], max_rows=5000)


def test_pipeline_does_not_change_the_snapshot(snap):
    before = snap.model_dump_json()
    run_pipeline(snap, [{"join": ["host", "type", "hosted"], "select": ["uid"]}])
    assert snap.model_dump_json() == before


class _WS:
    def __init__(self, root):
        self.allowed_directories = [root]


def test_provider_tool_reads_a_saved_snapshot(snap, tmp_path):
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snap.snapshot_id}.json").write_text(
        json.dumps(snap.model_dump(by_alias=True, mode="json")), encoding="utf-8"
    )
    provider = SemanticProvider(_WS(tmp_path))
    assert "snapshot_compute" in {t.name for t in provider.get_capabilities()}
    out = asyncio.run(provider.execute_tool("snapshot_compute", {
        "snapshot_id": snap.snapshot_id,
        "steps": [{"where": {"field": "category", "value": "OST_Doors"}, "aggregate": {"n": "count"}}],
    }))
    assert out["rows"] == [{"n": 2}]
    with pytest.raises(BridgeError, match="refused the pipeline"):
        asyncio.run(provider.execute_tool("snapshot_compute", {"snapshot_id": snap.snapshot_id, "steps": [{"bad": 1}]}))
    with pytest.raises(ValueError):
        asyncio.run(provider.execute_tool("snapshot_compute", {"snapshot_id": "../x", "steps": [{}]}))


# ------------------------------------------------------------------ spatial joins


def _boxed(uid, category, lo, hi):
    return ElementRecord(uid=uid, element_id=900, category=category, cls="FamilyInstance",
                         bbox=BBox(min=lo, max=hi))


@pytest.fixture
def spatial_snap(snap):
    snap.elements += [
        _boxed("box", "OST_GenericModel", [0.0, -1.0, 0.0], [11.0, 1.0, 5.0]),
        _boxed("column", "OST_StructuralColumns", [12.0, 0.0, 0.0], [12.5, 0.5, 4.0]),
    ]
    return snap


def _spatial_rows(snap, category, spec, select):
    # spatial runs before where in a step, so the rows are narrowed in an earlier step.
    return run_pipeline(snap, [
        {"name": "others", "where": {"field": "category", "op": "ne", "value": "OST_Levels"}},
        {"name": "mine", "where": {"field": "category", "value": category}},
        {"name": "out", "from": "$mine", "spatial": spec, "select": select},
    ])["rows"]


WALL = "c0326e0e-473d-4952-b8ec-f23696541f43-wall-1"
DOOR = "c0326e0e-473d-4952-b8ec-f23696541f44-door-1"


def test_spatial_overlaps_adds_matches_and_count(spatial_snap):
    """Doors and the elements their boxes touch; a door without a bbox matches nothing."""
    rows = _spatial_rows(spatial_snap, "OST_Doors", {"with": "$others", "test": "overlaps", "as": "near"},
                         ["uid", "near_count", "near"])
    by_uid = {r["uid"]: r for r in rows}
    assert sorted(m["uid"] for m in by_uid[DOOR]["near"]) == ["box", WALL]  # never itself
    assert by_uid[DOOR]["near_count"] == 2
    assert by_uid["door-2"]["near_count"] == 0 and by_uid["door-2"]["near"] == []


def test_spatial_contains_and_within(spatial_snap):
    contains = _spatial_rows(spatial_snap, "OST_GenericModel", {"with": "$others", "test": "contains"},
                             [{"field": "others_count", "as": "n"}])
    assert contains == [{"n": 2}]  # the wall and the door, not the column
    within = _spatial_rows(spatial_snap, "OST_Walls", {"with": "$others", "test": "within", "as": "in"},
                           [{"field": "in.0.uid", "as": "in"}, "in_count"])
    assert within == [{"in": "box", "in_count": 1}]


def test_spatial_within_distance_uses_the_gap_between_boxes(spatial_snap):
    def near_column(distance):
        rows = _spatial_rows(spatial_snap, "OST_StructuralColumns",
                             {"with": "$others", "test": "within_distance", "distance": distance, "as": "near"},
                             ["near"])
        return sorted(m["uid"] for m in rows[0]["near"])

    assert near_column(2) == ["box", WALL]  # the wall ends at x 10, the column starts at x 12
    assert near_column(1.9) == ["box"]  # the box ends at x 11
    assert near_column(0) == []


def test_spatial_malformed_bbox_never_matches(snap):
    snap.elements.append(ElementRecord(uid="bad", element_id=901, category="OST_Walls", cls="Wall",
                                       bbox=BBox(min=[5.0, 5.0, 5.0], max=[0.0, 0.0, 0.0])))
    rows = run_pipeline(snap, [
        {"name": "all"},
        {"from": "$all", "where": {"field": "uid", "value": "bad"},
         "spatial": {"with": "$all", "test": "within_distance", "distance": 1000}, "select": ["all_count"]},
    ])["rows"]
    assert rows == [{"all_count": 0}]


def test_spatial_pair_cap_is_enforced(spatial_snap, monkeypatch):
    # Rows without a bbox do not count: door-1 is the only boxed door, against 4 boxed others.
    monkeypatch.setattr(compute, "MAX_PAIRS", 4)
    assert len(_spatial_rows(spatial_snap, "OST_Doors", {"with": "$others", "test": "overlaps"}, ["uid"])) == 2
    monkeypatch.setattr(compute, "MAX_PAIRS", 3)
    with pytest.raises(QueryError, match=r"step 'out': spatial would compare 4 pairs, more than 3"):
        _spatial_rows(spatial_snap, "OST_Doors", {"with": "$others", "test": "overlaps"}, ["uid"])


def test_spatial_default_pair_cap():
    assert compute.MAX_PAIRS == 250_000


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"with": "$later", "test": "overlaps"}, "earlier step"),
        ({"with": "elements", "test": "overlaps"}, "earlier step"),
        ({"with": "$a", "test": "intersects"}, "unknown spatial test"),
        ({"with": "$a", "test": "within_distance"}, "needs 'distance'"),
        ({"with": "$a", "test": "within_distance", "distance": -1}, "needs 'distance'"),
        ({"with": "$a", "test": "within_distance", "distance": "5"}, "needs 'distance'"),
        ({"with": "$a", "test": "within_distance", "distance": 5000}, "needs 'distance'"),
        ({"with": "$a", "test": "overlaps", "distance": 1}, "only used with"),
        ({"with": "$a", "test": "overlaps", "as": "a.b"}, "plain name"),
        ({"with": "$a", "test": "overlaps", "code": "x"}, "spatial is"),
        ("$a", "spatial is"),
    ],
)
def test_malformed_spatial_is_refused(snap, spec, message):
    with pytest.raises(QueryError, match=f"step 'b': .*{message}"):
        run_pipeline(snap, [{"name": "a"}, {"name": "b", "spatial": spec}])


# ------------------------------------------------------------------ linked models


def _linked(snap, snapshot_id, rating):
    link = snap.model_copy(deep=True)
    link.snapshot_id = snapshot_id
    wall = next(e for e in link.elements if e.category == "OST_Walls")
    wall.params["Fire Rating"] = ParamVal(v=rating, storage="String")
    return link


def test_link_rows_carry_snapshot_id_and_join_in_their_own_snapshot(snap):
    links = {"LINK1": _linked(snap, "LINK1", "90")}
    out = run_pipeline(snap, [
        {"name": "host_doors", "where": {"field": "category", "value": "OST_Doors"}, "join": ["host"]},
        {"name": "link_doors", "from": "link:LINK1", "where": {"field": "category", "value": "OST_Doors"},
         "join": ["host"],
         "select": ["_snapshot_id", "params.Mark", {"field": "host.params.Fire Rating", "as": "wall"}]},
    ], load_snapshot=links.__getitem__)
    assert out["rows"] == [
        {"_snapshot_id": "LINK1", "params.Mark": "D-101", "wall": "90"},
        {"_snapshot_id": "LINK1", "params.Mark": "D-102", "wall": "90"},
    ]
    assert out["linked_snapshots"] == ["LINK1"]
    assert out["step_counts"]["host_doors"] == 2
    host = run_pipeline(snap, [{"where": {"field": "category", "value": "OST_Walls"}}])
    assert "_snapshot_id" not in host["rows"][0] and "linked_snapshots" not in host


def test_host_against_link_spatial_join(snap):
    links = {"LINK1": _linked(snap, "LINK1", "90")}
    rows = run_pipeline(snap, [
        {"name": "link_walls", "from": "link:LINK1", "where": {"field": "category", "value": "OST_Walls"}},
        {"where": {"field": "category", "value": "OST_Walls"},
         "spatial": {"with": "$link_walls", "test": "overlaps", "as": "clash"},
         "select": ["uid", {"field": "clash.0._snapshot_id", "as": "from"}, "clash_count"]},
    ], load_snapshot=links.__getitem__)["rows"]
    # The same uid in another snapshot is a different element, so it matches.
    assert rows == [{"uid": WALL, "from": "LINK1", "clash_count": 1}]


def test_link_limits_and_loader_errors(snap):
    loaded = []

    def load(snapshot_id):
        if snapshot_id == "missing":
            raise QueryError("not found")
        loaded.append(snapshot_id)
        return _linked(snap, snapshot_id, "60")

    same = [{"name": f"s{i}", "from": "link:A"} for i in range(3)]
    assert run_pipeline(snap, same, load_snapshot=load)["linked_snapshots"] == ["A"] and loaded == ["A"]
    many = [{"name": f"s{i}", "from": f"link:L{i}"} for i in range(MAX_LINKS + 1)]
    with pytest.raises(QueryError, match=f"at most {MAX_LINKS} linked snapshots"):
        run_pipeline(snap, many, load_snapshot=load)
    with pytest.raises(QueryError, match="step 'x': not found"):
        run_pipeline(snap, [{"name": "x", "from": "link:missing"}], load_snapshot=load)
    with pytest.raises(QueryError, match="not available"):
        run_pipeline(snap, [{"from": "link:A"}])
    with pytest.raises(QueryError, match="link:<snapshot_id>"):
        run_pipeline(snap, [{"from": "link:"}], load_snapshot=load)


def test_partial_link_marks_the_result_partial(snap):
    link = _linked(snap, "P", "60")
    link.counts["truncated"] = True
    out = run_pipeline(snap, [{"from": "link:P", "limit": 1}], load_snapshot=lambda _id: link)
    assert out["partial_snapshot"] is True


def test_pipeline_runs_on_saved_snapshot_json(snap):
    data = snap.model_dump(by_alias=True, mode="json")
    out = run_pipeline(data, [{"join": ["host"], "where": {"field": "host.category", "value": "OST_Walls"},
                               "aggregate": {"n": "count"}}])
    assert out["rows"] == [{"n": 2}] and out["snapshot_id"] == snap.snapshot_id


def test_validate_steps_checks_shape_without_a_model():
    validate_steps([{"name": "a"}, {"from": "$a", "spatial": {"with": "$a", "test": "overlaps"}}])
    with pytest.raises(QueryError, match="unknown op"):
        validate_steps([{"where": {"field": "x", "op": "regex", "value": "."}}])
    with pytest.raises(QueryError, match="not available"):
        validate_steps([{"from": "link:A"}])


# ------------------------------------------------------------------ saved queries


def _save(tmp_path, snapshot):
    (tmp_path / "snapshots").mkdir(exist_ok=True)
    (tmp_path / "snapshots" / f"{snapshot.snapshot_id}.json").write_text(
        json.dumps(snapshot.model_dump(by_alias=True, mode="json")), encoding="utf-8"
    )


def _query(tmp_path, name, document):
    (tmp_path / "queries").mkdir(exist_ok=True)
    path = tmp_path / "queries" / f"{name}.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
    return path


DOORS_QUERY = {
    "description": "Elements of one category whose Mark is in a list.",
    "params": {"category": "OST_Doors"},
    "steps": [
        {"name": "hits", "where": [{"field": "category", "value": {"$param": "category"}},
                                   {"field": "params.Mark", "op": "in", "value": {"$param": "marks"}}],
         "select": ["params.Mark"], "sort": "params.Mark"},
        {"name": "n", "from": "$hits", "aggregate": {"n": "count"}},
    ],
    "return": "hits",
}


def _compute(tmp_path, **arguments):
    provider = SemanticProvider(_WS(tmp_path))
    return asyncio.run(provider.execute_tool("snapshot_compute", arguments))


def test_saved_query_runs_with_params_and_defaults(snap, tmp_path):
    _save(tmp_path, snap)
    _query(tmp_path, "door_marks", DOORS_QUERY)
    out = _compute(tmp_path, snapshot_id=snap.snapshot_id, query="door_marks", params={"marks": ["D-102", "X"]})
    assert out["returned_step"] == "hits" and out["rows"] == [{"params.Mark": "D-102"}]
    out = _compute(tmp_path, snapshot_id=snap.snapshot_id, query="door_marks", params={"marks": ["D-101"]},
                   **{"return": "n"})
    assert out["rows"] == [{"n": 1}]
    out = _compute(tmp_path, snapshot_id=snap.snapshot_id, query="door_marks",
                   params={"marks": ["D-101"], "category": "OST_Walls"})
    assert out["rows"] == []


def test_saved_query_as_a_bare_list_of_steps(snap, tmp_path):
    _save(tmp_path, snap)
    _query(tmp_path, "count", [{"aggregate": {"n": "count"}}])
    assert _compute(tmp_path, snapshot_id=snap.snapshot_id, query="count")["rows"] == [{"n": len(snap.elements)}]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"query": "door_marks"}, "needs param 'marks'"),
        ({"query": "door_marks", "params": {"marks": [], "extra": 1}}, r"does not use params \['extra'\]"),
        ({"query": "door_marks", "params": {"bad name": 1}}, "param names"),
        ({"query": "door_marks", "params": ["x"]}, "params is an object"),
        ({"query": "door_marks", "steps": [{}]}, "either steps or query"),
        ({"steps": [{}], "params": {"a": 1}}, "pass query with them"),
        ({}, "pass steps, or query"),
        ({"query": "../evil"}, "plain name"),
        ({"query": "a/b"}, "plain name"),
        ({"query": "door_marks.json"}, "plain name"),
        ({"query": ""}, "plain name"),
        ({"query": 5}, "plain name"),
        ({"query": "absent"}, r"saved query 'absent' not found; expected queries/absent.json"),
    ],
)
def test_saved_query_refusals(snap, tmp_path, arguments, message):
    _save(tmp_path, snap)
    _query(tmp_path, "door_marks", DOORS_QUERY)
    with pytest.raises(BridgeError, match=message):
        _compute(tmp_path, snapshot_id=snap.snapshot_id, **arguments)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("{not json", "not valid JSON"),
        ('"text"', "JSON object with 'steps'"),
        ({"steps": [{"bad": 1}]}, r"step 'step1': unknown keys \['bad'\]"),
        ({"steps": [{}], "run": "x"}, r"unknown keys \['run'\]"),
        ({"steps": [{}], "return": 3}, "return is a step name"),
        ({"steps": [{}], "description": 3}, "description is text"),
        ({"steps": [{"where": {"field": "x", "value": {"$param": "p", "x": 1}}}], "params": {"p": 1}},
         "takes one name"),
        # A param value is put in as it is: a $param inside it is not filled again.
        ({"steps": [{"where": {"field": "x", "value": {"$param": "p"}}}],
          "params": {"p": {"$param": "q"}, "q": 1}}, "object value"),
    ],
)
def test_invalid_saved_query_files_are_refused(snap, tmp_path, document, message):
    _save(tmp_path, snap)
    _query(tmp_path, "q", document)
    with pytest.raises(BridgeError, match=message):
        _compute(tmp_path, snapshot_id=snap.snapshot_id, query="q")


def test_saved_query_text_is_never_templated():
    resolved = resolve_query("q", {"steps": [{"where": {"field": "name", "value": "$param x {$param}"}}]})
    assert resolved["steps"][0]["where"]["value"] == "$param x {$param}"


def test_saved_query_symlink_out_of_the_folder_is_refused(snap, tmp_path):
    _save(tmp_path, snap)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text(json.dumps([{"aggregate": {"n": "count"}}]), encoding="utf-8")
    (tmp_path / "queries").mkdir()
    try:
        (tmp_path / "queries" / "evil.json").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    with pytest.raises(BridgeError, match="plain name"):
        _compute(tmp_path, snapshot_id=snap.snapshot_id, query="evil")


def test_saved_query_too_large_is_refused(snap, tmp_path):
    _save(tmp_path, snap)
    _query(tmp_path, "big", json.dumps([{"name": "x" * 300_000}]))
    with pytest.raises(BridgeError, match="larger than"):
        _compute(tmp_path, snapshot_id=snap.snapshot_id, query="big")


def test_provider_links_saved_snapshots(snap, tmp_path):
    _save(tmp_path, snap)
    _save(tmp_path, _linked(snap, "LINKSNAP", "90"))
    out = _compute(tmp_path, snapshot_id=snap.snapshot_id, steps=[
        {"from": "link:LINKSNAP", "where": {"field": "category", "value": "OST_Walls"},
         "select": ["_snapshot_id", "params.Fire Rating"]},
    ])
    assert out["rows"] == [{"_snapshot_id": "LINKSNAP", "params.Fire Rating": "90"}]
    with pytest.raises(BridgeError, match="link:NOPE: Snapshot 'NOPE' not found"):
        _compute(tmp_path, snapshot_id=snap.snapshot_id, steps=[{"from": "link:NOPE"}])
    with pytest.raises(BridgeError, match="plain snapshot name"):
        _compute(tmp_path, snapshot_id=snap.snapshot_id, steps=[{"from": "link:../snapshots/x"}])
