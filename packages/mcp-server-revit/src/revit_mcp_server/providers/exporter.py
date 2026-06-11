from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from ..errors import WorkspaceViolation
from ..security.workspace import WorkspaceMonitor
from .base import AECProvider, ProviderTool
from .registry import ProviderRegistry

logger = logging.getLogger(__name__)


class SQLiteExporterProvider(AECProvider):
    def __init__(self, workspace: WorkspaceMonitor, registry: ProviderRegistry) -> None:
        self.workspace = workspace
        self.registry = registry
        self._init_capabilities()

    def get_identity(self) -> str:
        return "exporter"

    def get_capabilities(self) -> List[ProviderTool]:
        return self._capabilities

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy", "provider": "exporter"}

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        normalized = name.replace(".", "_")
        if normalized == "exporter_db_health":
            return await self.check_health()
        elif normalized == "exporter_to_sqlite":
            return self._export_to_sqlite(arguments)
        elif normalized == "exporter_graph_to_sqlite":
            return self._export_graph_to_sqlite(arguments)
        raise ValueError(f"Unknown exporter tool '{name}'")

    def _init_capabilities(self) -> None:
        self._capabilities = [
            ProviderTool(
                name="exporter_db_health",
                description="Check health and readiness of the local database exporter.",
                inputSchema={"type": "object", "properties": {}},
            ),
            ProviderTool(
                name="exporter_to_sqlite",
                description="Export a structured payload of BIM elements, parameters, and relationships to a local SQLite database in the workspace.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "db_path": {
                            "type": "string",
                            "description": "Workspace-relative or absolute path to the output .db file.",
                        },
                        "elements": {
                            "type": "array",
                            "description": "List of elements and their parameters.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "The unique identifier (GUID / element ID) of the element."},
                                    "name": {"type": "string", "description": "Human-readable name of the element."},
                                    "category": {"type": "string", "description": "The category classification (e.g. Walls, Windows)."},
                                    "type_name": {"type": "string", "description": "The type or family name of the element."},
                                    "parameters": {
                                        "type": "object",
                                        "description": "Flat dictionary of parameter name/value attributes.",
                                    },
                                },
                                "required": ["id"],
                            },
                        },
                        "relations": {
                            "type": "array",
                            "description": "Optional relationships between elements.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source_id": {"type": "string", "description": "Source element identifier."},
                                    "target_id": {"type": "string", "description": "Target element identifier."},
                                    "relation_type": {"type": "string", "description": "Type of relation (e.g. SUPPORTED_BY)."},
                                    "attributes": {
                                        "type": "object",
                                        "description": "Optional attributes associated with the relationship.",
                                    },
                                },
                                "required": ["source_id", "target_id", "relation_type"],
                            },
                        },
                    },
                    "required": ["db_path", "elements"],
                    "additionalProperties": False,
                },
            ),
            ProviderTool(
                name="exporter_graph_to_sqlite",
                description="Extract the active semantic network graph and dump its nodes, properties, and typed edges to a local SQLite database in the workspace.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "db_path": {
                            "type": "string",
                            "description": "Workspace-relative or absolute path to the output .db file.",
                        }
                    },
                    "required": ["db_path"],
                    "additionalProperties": False,
                },
            ),
        ]

    def _export_to_sqlite(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        db_path_str = arguments["db_path"]
        elements = arguments["elements"]
        relations = arguments.get("relations", [])

        try:
            db_file = self.workspace.assert_in_workspace(Path(db_path_str))
        except WorkspaceViolation as exc:
            raise ValueError("Database path is outside the allowed workspace.") from exc

        return self._write_database(db_file, elements, relations)

    def _export_graph_to_sqlite(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        db_path_str = arguments["db_path"]

        try:
            db_file = self.workspace.assert_in_workspace(Path(db_path_str))
        except WorkspaceViolation as exc:
            raise ValueError("Database path is outside the allowed workspace.") from exc

        graph_provider = self.registry.get_provider("graph")
        if not graph_provider:
            raise ValueError("SemanticGraphProvider is not registered on the server.")

        g = getattr(graph_provider, "graph", None)
        if g is None:
            raise ValueError("Could not access graph on SemanticGraphProvider.")

        elements: List[Dict[str, Any]] = []
        relations: List[Dict[str, Any]] = []

        for node_id, data in g.nodes(data=True):
            el = {
                "id": str(node_id),
                "name": str(data.get("name", node_id)),
                "category": str(data.get("type", "unknown")),
                "placeholder": bool(data.get("placeholder", False)),
                "parameters": {
                    k: v for k, v in data.items() if k not in {"name", "type", "placeholder"}
                }
            }
            elements.append(el)

        for u, v, key, data in g.edges(keys=True, data=True):
            rel = {
                "source_id": str(u),
                "target_id": str(v),
                "relation_type": str(data.get("relation", "CONNECTED_TO")),
                "attributes": {
                    k: v for k, v in data.items() if k != "relation"
                }
            }
            relations.append(rel)

        return self._write_database(db_file, elements, relations)

    def _write_database(
        self,
        db_file: Path,
        elements: List[Dict[str, Any]],
        relations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        db_file.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS elements (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    category TEXT,
                    type_name TEXT,
                    placeholder INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS parameters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    element_id TEXT,
                    name TEXT,
                    value TEXT,
                    value_type TEXT,
                    FOREIGN KEY(element_id) REFERENCES elements(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT,
                    target_id TEXT,
                    relation_type TEXT,
                    attributes_json TEXT,
                    FOREIGN KEY(source_id) REFERENCES elements(id),
                    FOREIGN KEY(target_id) REFERENCES elements(id)
                )
            """)

            cursor.execute("DELETE FROM relations")
            cursor.execute("DELETE FROM parameters")
            cursor.execute("DELETE FROM elements")

            element_count = 0
            parameter_count = 0
            relation_count = 0

            for el in elements:
                el_id = str(el["id"])
                name = el.get("name")
                category = el.get("category")
                type_name = el.get("type_name")
                placeholder = 1 if el.get("placeholder") else 0

                cursor.execute(
                    "INSERT INTO elements (id, name, category, type_name, placeholder) VALUES (?, ?, ?, ?, ?)",
                    (el_id, name, category, type_name, placeholder)
                )
                element_count += 1

                params = el.get("parameters", {})
                if isinstance(params, dict):
                    for k, v in params.items():
                        val_str = str(v) if v is not None else ""
                        val_type = type(v).__name__ if v is not None else "NoneType"
                        cursor.execute(
                            "INSERT INTO parameters (element_id, name, value, value_type) VALUES (?, ?, ?, ?)",
                            (el_id, k, val_str, val_type)
                        )
                        parameter_count += 1

            for rel in relations:
                src = str(rel["source_id"])
                tgt = str(rel["target_id"])
                rel_type = str(rel["relation_type"])
                attrs = rel.get("attributes", {})
                attrs_str = json.dumps(attrs) if attrs else None

                cursor.execute(
                    "INSERT INTO relations (source_id, target_id, relation_type, attributes_json) VALUES (?, ?, ?, ?)",
                    (src, tgt, rel_type, attrs_str)
                )
                relation_count += 1

            conn.commit()
            return {
                "status": "success",
                "db_path": str(db_file),
                "exported": {
                    "elements": element_count,
                    "parameters": parameter_count,
                    "relations": relation_count,
                }
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    async def shutdown(self) -> None:
        pass
