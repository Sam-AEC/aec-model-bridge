from __future__ import annotations

import json
import re
from typing import Any, Dict, List
import uuid

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.base import AECProvider, ProviderTool
from revit_mcp_server.security.safe_paths import safe_child, snapshot_file
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.semantic import engine
from revit_mcp_server.semantic.models import Snapshot

# Saved snapshot_compute queries: <workspace>/queries/<name>.json
QUERIES_DIRNAME = "queries"
QUERY_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
MAX_QUERY_BYTES = 256_000

class SemanticProvider(AECProvider):
    def __init__(self, workspace: WorkspaceMonitor, registry: Any = None):
        self.workspace = workspace
        self.registry = registry
        self._init_capabilities()

    def get_identity(self) -> str:
        return "semantic"

    def get_capabilities(self) -> List[ProviderTool]:
        return self._capabilities

    async def check_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider": "semantic"
        }

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "snapshot_take":
            return await self._snapshot_take(arguments)
        elif name == "snapshot_query":
            return await self._snapshot_query(arguments)
        elif name == "snapshot_diff":
            return await self._snapshot_diff(arguments)
        elif name == "snapshot_compute":
            return await self._snapshot_compute(arguments)
        else:
            raise BridgeError(f"Unknown tool '{name}' on semantic provider")

    def _init_capabilities(self):
        self._capabilities = [
            ProviderTool(
                name="snapshot_take",
                description="Extract and save a semantic BIM snapshot of the active Revit model. Large models are captured within a size and time limit; pass categories to capture only what a check needs.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "categories": {"type": "array", "items": {"type": "string"}},
                        "max_elements": {"type": "integer", "minimum": 1},
                        "params": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1, "maxLength": engine.SNAPSHOT_MAX_PARAM_NAME},
                            "maxItems": engine.SNAPSHOT_MAX_PARAMS,
                            "description": "Read only these parameters (names such as \"Mark\", or built-in ids such as ALL_MODEL_MARK). The snapshot is then partial for checks that read other parameters.",
                        },
                        "slice_size": {
                            "type": "integer",
                            "minimum": engine.SLICE_SIZE_MIN,
                            "maximum": engine.SLICE_SIZE_MAX,
                            "description": "Extract in slices of about this many elements per Revit turn, so Revit stays responsive; the slices are assembled into one snapshot.",
                        },
                        "base_snapshot_id": {
                            "type": "string",
                            "description": "Incremental capture: re-read only elements changed since this snapshot and merge into a new full snapshot. Falls back to a full capture and says why.",
                        },
                    },
                    "required": [],
                }
            ),
            ProviderTool(
                name="snapshot_query",
                description="Query element records within a saved snapshot using filter DSL.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "snapshot_id": {"type": "string"},
                        "filter": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string"},
                                "family": {"type": "string"},
                                "type_name": {"type": "string"},
                                "level_uid": {"type": "string"},
                                "placed": {"type": "boolean"},
                                "parameter": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "empty": {"type": "boolean"},
                                        "value": {"type": "string"}
                                    },
                                    "required": ["name"]
                                }
                            }
                        }
                    },
                    "required": ["snapshot_id", "filter"]
                }
            ),
            ProviderTool(
                name="snapshot_compute",
                description=(
                    "Answer a model question in one call: run a read-only pipeline of named steps over a saved "
                    "snapshot and return only the result. Each step reads 'elements', 'types', 'relations', "
                    "'$<earlier step>' or 'link:<snapshot_id>' (elements of another saved snapshot, rows carry "
                    "_snapshot_id), then join (type, host, level, room, group, hosted, relation_out, "
                    "relation_in), spatial (bounding-box overlaps, contains, within or within_distance against "
                    "an earlier step), where (field/op/value with all, any, not; value {\"field\": path} "
                    "compares two fields), group_by with aggregate (count, sum, avg, min, max, distinct, list), "
                    "sort, select and limit. Paths are dotted: 'params.Fire Rating', 'host.params.Fire Rating', "
                    "'type.family'. Pass query to run <workspace>/queries/<name>.json with params. Use it "
                    "instead of many list or inspect calls. Never touches Revit."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "snapshot_id": {"type": "string"},
                        "query": {
                            "type": "string",
                            "description": "Saved query name: runs <workspace>/queries/<name>.json instead of steps.",
                        },
                        "params": {
                            "type": "object",
                            "description": "Values for {\"$param\": name} placeholders in a saved query.",
                        },
                        "steps": {
                            "type": "array",
                            "description": "Named steps run in order; a step reads a source or '$<earlier step>'.",
                            "minItems": 1,
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "from": {"type": "string", "default": "elements"},
                                    "join": {"type": "array", "items": {}},
                                    "spatial": {
                                        "type": "object",
                                        "description": "{\"with\": \"$step\", \"test\": overlaps|contains|within|"
                                                       "within_distance, \"distance\": feet, \"as\": name}",
                                    },
                                    "where": {},
                                    "group_by": {"type": "array", "items": {"type": "string"}},
                                    "aggregate": {"type": "object"},
                                    "sort": {"type": "array", "items": {}},
                                    "select": {"type": "array", "items": {}},
                                    "limit": {"type": "integer", "minimum": 0},
                                },
                            },
                        },
                        "return": {"type": "string", "description": "Step to return; default the last."},
                        "max_rows": {
                            "type": "integer", "minimum": 1, "maximum": 1000, "default": 100,
                            "description": "Rows returned from the result step; row_count still gives the total.",
                        },
                    },
                    "required": ["snapshot_id"],
                },
            ),
            ProviderTool(
                name="snapshot_diff",
                description="Compare two saved snapshots and identify differences (added, deleted, modified).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "snapshot_a_id": {"type": "string"},
                        "snapshot_b_id": {"type": "string"}
                    },
                    "required": ["snapshot_a_id", "snapshot_b_id"]
                }
            )
        ]

    async def _snapshot_take(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # Call bridge server / extract snapshot
        revit_prov = None
        if self.registry:
            revit_prov = self.registry.get_provider("revit")
            
        options = {
            k: arguments[k]
            for k in ("categories", "max_elements", "params", "slice_size", "base_snapshot_id")
            if arguments.get(k) is not None
        }
        snapshot = await engine.snapshot_take(self.workspace, revit_prov, options)
        
        # Identity mapper integration: register mappings in memory
        if self.registry:
            mapper = self.registry.get_provider("mapper")
            if mapper:
                mappings = []
                import ifcopenshell.guid  # lazy: heavy import, only needed here

                for el in snapshot.elements:
                    if el.uid:
                        # Extract GUID prefix deterministically
                        guid_part = el.uid[:36]
                        try:
                            uuid_obj = uuid.UUID(guid_part)
                            ifc_guid = ifcopenshell.guid.compress(uuid_obj.hex)
                        except Exception:
                            ifc_guid = None
                        
                        mappings.append({
                            "revit_unique_id": el.uid,
                            "ifc_guid": ifc_guid
                        })
                if mappings:
                    mapper._register_mapping({"mappings": mappings})
                    
        counts = snapshot.counts
        result: Dict[str, Any] = {
            "status": "success",
            "snapshot_id": snapshot.snapshot_id,
            "taken_at": snapshot.taken_at.isoformat(),
            "elements_count": len(snapshot.elements),
            "truncated": bool(counts.get("truncated")),
            "candidates": counts.get("candidates"),
            "note": (
                "Partial snapshot: the model is larger than one capture allows. Re-run snapshot_take with "
                "categories (for example [\"Doors\", \"Rooms\"]) for the elements a check needs, and do not "
                "read results from this snapshot as covering the whole model."
            ) if counts.get("truncated") else None,
        }
        if counts.get("params"):
            result["params"] = counts["params"]
        if counts.get("sliced"):
            result["slices"] = counts.get("slices")
            if counts.get("changed_during_capture"):
                result["changed_during_capture"] = True
                result["note"] = ((result["note"] + " ") if result["note"] else "") + (
                    "The model changed while the slices were read, so the snapshot mixes states from before "
                    "and after that change. Take it again before comparing or auditing.")
        if arguments.get("base_snapshot_id") is not None:
            result["incremental"] = bool(counts.get("incremental"))
            result["base_snapshot_id"] = arguments["base_snapshot_id"]
            if counts.get("incremental"):
                result["incremental_changes"] = counts.get("incremental_changes")
            else:
                result["incremental_reason"] = counts.get("incremental_reason")
        return result

    async def _snapshot_query(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        snapshot_id = arguments["snapshot_id"]
        filter_dsl = arguments["filter"]
        
        snapshot = self._load_snapshot(snapshot_id)
        elements = engine.snapshot_query(snapshot, filter_dsl)
        
        return {
            "snapshot_id": snapshot_id,
            "matches_count": len(elements),
            "elements": [el.model_dump(by_alias=True) for el in elements]
        }

    async def _snapshot_diff(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        a_id = arguments["snapshot_a_id"]
        b_id = arguments["snapshot_b_id"]
        
        snap_a = self._load_snapshot(a_id)
        snap_b = self._load_snapshot(b_id)
        
        diff = engine.snapshot_diff(snap_a, snap_b)
        
        return {
            "snapshot_a_id": a_id,
            "snapshot_b_id": b_id,
            "added_count": len(diff["added"]),
            "deleted_count": len(diff["deleted"]),
            "modified_count": len(diff["modified"]),
            "added": [el.model_dump(by_alias=True) for el in diff["added"]],
            "deleted": diff["deleted"],
            "modified": [el.model_dump(by_alias=True) for el in diff["modified"]]
        }

    async def _snapshot_compute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from revit_mcp_server.semantic.compute import QueryError, resolve_query, run_pipeline

        snapshot = self._load_snapshot(arguments["snapshot_id"])

        def load_link(snapshot_id: str) -> Snapshot:
            try:
                return self._load_snapshot(snapshot_id)
            except ValueError as exc:  # hostile or malformed id (snapshot_file)
                raise QueryError(f"link:{snapshot_id}: {exc}") from exc
            except BridgeError as exc:
                raise QueryError(f"link:{snapshot_id}: {exc}") from exc

        try:
            steps = arguments.get("steps")
            return_step = arguments.get("return")
            query = arguments.get("query")
            if query is not None:
                if steps is not None:
                    raise QueryError("pass either steps or query, not both")
                resolved = resolve_query(query, self._read_query(query), arguments.get("params"))
                steps = resolved["steps"]
                return_step = return_step or resolved["return"]
            elif arguments.get("params") is not None:
                raise QueryError("params fill a saved query; pass query with them")
            elif steps is None:
                raise QueryError("pass steps, or query with the name of a saved query")
            return run_pipeline(
                snapshot,
                steps,
                return_step=return_step,
                max_rows=arguments.get("max_rows", 100),
                load_snapshot=load_link,
            )
        except QueryError as exc:
            raise BridgeError(f"snapshot_compute refused the pipeline: {exc}") from exc

    def _read_query(self, name: Any) -> Any:
        """Parsed JSON of <workspace>/queries/<name>.json. QueryError when missing or invalid."""
        from revit_mcp_server.semantic.compute import QueryError

        def refuse(_reason: str) -> Exception:
            return QueryError(
                "query is the plain name of a file in the workspace queries folder: letters, digits, "
                "'_' and '-', without '.json'"
            )

        root = self.workspace.allowed_directories[0]
        path = safe_child(root, name, ".json", QUERY_NAME_RE, refuse, subdir=QUERIES_DIRNAME)
        if not path.is_file():
            raise QueryError(f"saved query '{name}' not found; expected {QUERIES_DIRNAME}/{name}.json in the workspace")
        if path.stat().st_size > MAX_QUERY_BYTES:
            raise QueryError(f"saved query '{name}' is larger than {MAX_QUERY_BYTES} bytes")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (UnicodeDecodeError, ValueError) as exc:
            raise QueryError(f"saved query '{name}' is not valid JSON: {exc}") from exc

    def _load_snapshot(self, snapshot_id: str) -> Snapshot:
        snapshots_dir = self.workspace.allowed_directories[0] / "snapshots"
        snapshot_path = snapshot_file(snapshots_dir, snapshot_id)  # ValueError for a hostile id
        
        if not snapshot_path.exists():
            raise BridgeError(f"Snapshot '{snapshot_id}' not found in workspace snapshots directory")
            
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Snapshot(**data)
        except Exception as e:
            raise BridgeError(f"Failed to load snapshot '{snapshot_id}': {e}")

    async def shutdown(self) -> None:
        pass
