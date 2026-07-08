from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from revit_mcp_server.providers.graph import SemanticGraphProvider  # noqa: E402


def sample_graph_payload():
    return {
        "nodes": [
            {
                "id": "wall-1",
                "type": "Wall",
                "attributes": {"load_bearing": True},
                "aabb": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
            },
            {
                "id": "wall-2",
                "type": "Wall",
                "attributes": {"load_bearing": True},
                "aabb": {"min": [0.5, 0.5, 0.5], "max": [1.5, 1.5, 1.5]},
            },
            {
                "id": "slab-1",
                "type": "Slab",
                "attributes": {"requires_support": True},
                "aabb": {"min": [3.0, 0.0, 0.0], "max": [4.0, 1.0, 1.0]},
            },
            {
                "id": "slab-2",
                "type": "Slab",
                "attributes": {"requires_support": True},
                "aabb": {"min": [5.0, 0.0, 0.0], "max": [6.0, 1.0, 1.0]},
            },
            {
                "id": "beam-1",
                "type": "Beam",
                "attributes": {"load_bearing": False, "is_support": True},
                "aabb": {"min": [3.0, 0.0, -1.0], "max": [4.0, 1.0, 0.0]},
            },
            {
                "id": "pipe-1",
                "type": "Pipe",
                "attributes": {},
                "aabb": {"min": [10.0, 10.0, 10.0], "max": [11.0, 11.0, 11.0]},
            },
            {
                "id": "material-1",
                "type": "Material",
                "attributes": {},
                "aabb": {"min": [20.0, 20.0, 20.0], "max": [21.0, 21.0, 21.0]},
            },
        ],
        "edges": [
            {"source": "wall-1", "target": "wall-2", "relation": "CONNECTED_TO"},
            {"source": "wall-1", "target": "slab-1", "relation": "ADJACENT_TO"},
            {"source": "slab-1", "target": "beam-1", "relation": "SUPPORTED_BY"},
        ],
    }


@pytest.mark.anyio
async def test_graph_compile_relations_and_health():
    provider = SemanticGraphProvider()

    compiled = await provider.execute_tool("graph_compile", sample_graph_payload())
    assert compiled["status"] == "success"
    assert compiled["compiled"]["nodes_received"] == 7
    assert compiled["compiled"]["edges_received"] == 3
    assert compiled["compiled"]["nodes_total"] == 7
    assert compiled["compiled"]["edges_total"] == 3

    health = await provider.check_health()
    assert health["status"] == "healthy"
    assert health["nodes"] == 7
    assert health["edges"] == 3
    assert health["relation_counts"] == {
        "ADJACENT_TO": 1,
        "CONNECTED_TO": 1,
        "SUPPORTED_BY": 1,
    }

    added = await provider.execute_tool(
        "graph_add_relation",
        {
            "source_id": "wall-2",
            "target_id": "material-1",
            "relation": "HAS_MATERIAL",
            "attributes": {"confidence": 1.0},
        },
    )
    assert added["status"] == "success"
    assert added["relation"]["relation"] == "HAS_MATERIAL"
    assert added["relation"]["source_id"] == "wall-2"

    query = await provider.execute_tool(
        "graph_query_relations",
        {
            "node_id": "wall-1",
            "direction": "outgoing",
            "limit": 1,
        },
    )
    assert query["status"] == "success"
    assert query["count"] == 1
    assert query["total"] == 2
    assert query["truncated"] is True
    assert query["relations"][0]["source_id"] == "wall-1"
    assert query["relations"][0]["relation"] == "ADJACENT_TO"

    repeat = await provider.execute_tool(
        "graph_query_relations",
        {"node_id": "wall-1", "direction": "outgoing", "limit": 1},
    )
    assert repeat == query


@pytest.mark.anyio
async def test_graph_audits():
    provider = SemanticGraphProvider()
    await provider.execute_tool("graph_compile", sample_graph_payload())
    await provider.execute_tool(
        "graph_add_relation",
        {
            "source_id": "wall-2",
            "target_id": "material-1",
            "relation": "HAS_MATERIAL",
        },
    )

    clash_audit = await provider.execute_tool(
        "graph_audit_clashes",
        {
            "node_ids": ["wall-1", "wall-2", "material-1"],
            "tolerance": 0.0,
            "limit": 10,
        },
    )
    assert clash_audit["status"] == "success"
    assert clash_audit["count"] == 1
    assert clash_audit["total"] == 1
    assert clash_audit["clashes"][0]["node_a"] == "wall-1"
    assert clash_audit["clashes"][0]["node_b"] == "wall-2"

    disconnected = await provider.execute_tool(
        "graph_audit_disconnected",
        {
            "node_types": ["Wall", "Pipe"],
            "relation_types": ["CONNECTED_TO", "ADJACENT_TO"],
            "min_degree": 1,
            "limit": 10,
        },
    )
    assert disconnected["status"] == "success"
    assert disconnected["disconnected_nodes"] == ["pipe-1"]
    assert disconnected["components"] == [["pipe-1"], ["wall-1", "wall-2"]]

    structural = await provider.execute_tool(
        "graph_audit_structural_loads",
        {
            "node_types": ["Slab", "Beam"],
            "limit": 10,
        },
    )
    assert structural["status"] == "success"
    assert any(issue["issue"] == "missing_support" and issue["node_id"] == "slab-2" for issue in structural["issues"])
    assert all(not (issue["issue"] == "missing_support" and issue["node_id"] == "slab-1") for issue in structural["issues"])
    assert any(issue["issue"] == "unsupported_support_target" and issue["target_id"] == "beam-1" for issue in structural["issues"])
    assert any(issue["issue"] == "support_flag_conflict" and issue["node_id"] == "beam-1" for issue in structural["issues"])


@pytest.mark.anyio
async def test_graph_invalid_data_and_atomic_compile():
    provider = SemanticGraphProvider()
    baseline = sample_graph_payload()
    await provider.execute_tool("graph_compile", baseline)
    before_health = await provider.check_health()
    before_query = await provider.execute_tool(
        "graph_query_relations",
        {"node_id": "wall-1", "direction": "outgoing", "limit": 10},
    )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_compile",
            {
                "nodes": baseline["nodes"],
                "edges": [
                    {"source": "wall-1", "target": "missing-node", "relation": "CONNECTED_TO"}
                ],
            },
        )

    after_health = await provider.check_health()
    after_query = await provider.execute_tool(
        "graph_query_relations",
        {"node_id": "wall-1", "direction": "outgoing", "limit": 10},
    )
    assert after_health == before_health
    assert after_query == before_query

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_add_relation",
            {
                "source_id": "wall-1",
                "target_id": "wall-2",
                "relation": "INVALID_RELATION",
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_compile",
            {
                "nodes": [{"id": "", "type": "Wall"}],
                "edges": [],
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_compile",
            {
                "nodes": [{"id": 1.5, "type": "Wall"}],
                "edges": [],
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_compile",
            {
                "nodes": [{"id": {"value": "bad"}, "type": "Wall"}],
                "edges": [],
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_compile",
            {
                "nodes": [{"id": "bad-aabb", "aabb": {"min": [1, 0, 0], "max": [0, 1, 1]}}],
                "edges": [],
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_compile",
            {
                "nodes": {},
                "edges": [],
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_compile",
            {
                "nodes": [],
                "edges": {},
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_audit_clashes",
            {
                "nodes": {},
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_audit_disconnected",
            {
                "node_ids": "wall-1",
            },
        )

    with pytest.raises(ValueError):
        await provider.execute_tool(
            "graph_audit_structural_loads",
            {
                "node_types": "Wall",
            },
        )
