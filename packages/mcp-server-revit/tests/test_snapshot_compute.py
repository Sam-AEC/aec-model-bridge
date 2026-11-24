"""snapshot_compute: read-only query pipelines over a saved snapshot."""

import asyncio
import json

import pytest

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.semantic_provider import SemanticProvider
from revit_mcp_server.semantic import engine
from revit_mcp_server.semantic.compute import MAX_STEPS, QueryError, get_path, run_pipeline
from revit_mcp_server.semantic.models import ElementRecord, ParamVal, TypeRecord


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
