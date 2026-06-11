from __future__ import annotations

import sqlite3
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revit_mcp_server.providers.exporter import SQLiteExporterProvider
from revit_mcp_server.providers.graph import SemanticGraphProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security.workspace import WorkspaceMonitor


def test_exporter_health(tmp_path: Path):
    workspace = WorkspaceMonitor([tmp_path])
    registry = ProviderRegistry()
    provider = SQLiteExporterProvider(workspace=workspace, registry=registry)
    
    # Run sync health check
    import asyncio
    health = asyncio.run(provider.check_health())
    assert health["status"] == "healthy"
    assert health["provider"] == "exporter"


def test_exporter_to_sqlite(tmp_path: Path):
    workspace = WorkspaceMonitor([tmp_path])
    registry = ProviderRegistry()
    provider = SQLiteExporterProvider(workspace=workspace, registry=registry)
    
    db_file = tmp_path / "model.db"
    
    elements = [
        {
            "id": "wall-1",
            "name": "Generic Wall 1",
            "category": "Walls",
            "type_name": "Wall-Type-A",
            "parameters": {
                "Unconnected Height": 3000,
                "Structural": True,
                "Comments": "Audit ready"
            }
        },
        {
            "id": "door-1",
            "name": "Timber Door",
            "category": "Doors",
            "type_name": "Door-Type-B",
            "parameters": {
                "Width": 900,
                "Height": 2100
            }
        }
    ]
    
    relations = [
        {
            "source_id": "door-1",
            "target_id": "wall-1",
            "relation_type": "CONTAINED_IN",
            "attributes": {"offset": 120}
        }
    ]
    
    import asyncio
    res = asyncio.run(provider.execute_tool(
        "exporter_to_sqlite",
        {
            "db_path": str(db_file),
            "elements": elements,
            "relations": relations
        }
    ))
    
    assert res["status"] == "success"
    assert Path(res["db_path"]).exists()
    
    # Query database and assert correctness
    conn = sqlite3.connect(res["db_path"])
    cursor = conn.cursor()
    
    # Check elements table
    cursor.execute("SELECT id, name, category, type_name, placeholder FROM elements ORDER BY id")
    rows = cursor.fetchall()
    assert len(rows) == 2
    assert rows[0] == ("door-1", "Timber Door", "Doors", "Door-Type-B", 0)
    assert rows[1] == ("wall-1", "Generic Wall 1", "Walls", "Wall-Type-A", 0)
    
    # Check parameters table
    cursor.execute("SELECT element_id, name, value, value_type FROM parameters ORDER BY element_id, name")
    param_rows = cursor.fetchall()
    assert len(param_rows) == 5
    assert param_rows[0] == ("door-1", "Height", "2100", "int")
    assert param_rows[4] == ("wall-1", "Unconnected Height", "3000", "int")
    
    # Check relations table
    cursor.execute("SELECT source_id, target_id, relation_type, attributes_json FROM relations")
    rel_rows = cursor.fetchall()
    assert len(rel_rows) == 1
    assert rel_rows[0][0] == "door-1"
    assert rel_rows[0][1] == "wall-1"
    assert rel_rows[0][2] == "CONTAINED_IN"
    assert json.loads(rel_rows[0][3]) == {"offset": 120}
    
    conn.close()


def test_exporter_graph_to_sqlite(tmp_path: Path):
    workspace = WorkspaceMonitor([tmp_path])
    registry = ProviderRegistry()
    
    # Register semantic graph provider and compile a graph
    graph_provider = SemanticGraphProvider()
    registry.register(graph_provider)
    
    nodes = [
        {
            "id": "column-1",
            "type": "Columns",
            "attributes": {"load_bearing": True, "requires_support": False}
        },
        {
            "id": "beam-1",
            "type": "Structural Framing",
            "attributes": {"load_bearing": True, "requires_support": True}
        }
    ]
    edges = [
        {
            "source": "beam-1",
            "target": "column-1",
            "type": "SUPPORTED_BY",
            "attributes": {"span": 6000.0}
        }
    ]
    
    import asyncio
    compile_res = asyncio.run(graph_provider.execute_tool(
        "graph_compile",
        {"nodes": nodes, "edges": edges, "allow_dangling_edges": False}
    ))
    assert compile_res["status"] == "success"
    
    # Register exporter provider
    exporter_provider = SQLiteExporterProvider(workspace=workspace, registry=registry)
    registry.register(exporter_provider)
    
    db_file = tmp_path / "graph_export.db"
    res = asyncio.run(exporter_provider.execute_tool(
        "exporter_graph_to_sqlite",
        {"db_path": str(db_file)}
    ))
    assert res["status"] == "success"
    
    # Query database and verify schema contents
    conn = sqlite3.connect(res["db_path"])
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, category, placeholder FROM elements ORDER BY id")
    elements = cursor.fetchall()
    assert len(elements) == 2
    assert elements[0] == ("beam-1", "Structural Framing", 0)
    assert elements[1] == ("column-1", "Columns", 0)
    
    cursor.execute("SELECT element_id, name, value FROM parameters ORDER BY element_id, name")
    params = cursor.fetchall()
    assert len(params) == 4
    assert params[0] == ("beam-1", "load_bearing", "True")
    assert params[1] == ("beam-1", "requires_support", "True")
    assert params[2] == ("column-1", "load_bearing", "True")
    assert params[3] == ("column-1", "requires_support", "False")
    
    cursor.execute("SELECT source_id, target_id, relation_type, attributes_json FROM relations")
    relations = cursor.fetchall()
    assert len(relations) == 1
    assert relations[0][0] == "beam-1"
    assert relations[0][1] == "column-1"
    assert relations[0][2] == "SUPPORTED_BY"
    assert json.loads(relations[0][3]) == {"span": 6000.0}
    
    conn.close()


def test_exporter_workspace_bounds(tmp_path: Path):
    workspace = WorkspaceMonitor([tmp_path])
    registry = ProviderRegistry()
    provider = SQLiteExporterProvider(workspace=workspace, registry=registry)
    
    # Outside allowed directory
    bad_db_path = tmp_path.parent / "unsafe.db"
    
    import asyncio
    with pytest.raises(ValueError, match="Database path is outside"):
        asyncio.run(provider.execute_tool(
            "exporter_to_sqlite",
            {
                "db_path": str(bad_db_path),
                "elements": []
            }
        ))
        
    with pytest.raises(ValueError, match="Database path is outside"):
        asyncio.run(provider.execute_tool(
            "exporter_graph_to_sqlite",
            {"db_path": str(bad_db_path)}
        ))
