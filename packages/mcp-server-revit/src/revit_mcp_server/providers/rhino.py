from __future__ import annotations

import base64
import os
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import httpx

from ..errors import BridgeError, WorkspaceViolation
from ..security.workspace import WorkspaceMonitor
from .base import AECProvider, ProviderTool


class RhinoProvider(AECProvider):
    SUPPORTED_DEFINITION_EXTENSIONS = {".gh", ".ghx"}
    SUPPORTED_GEOMETRY_EXTENSIONS = {".3dm"}

    def __init__(
        self,
        workspace: WorkspaceMonitor,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_header: str = "RhinoComputeKey",
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        grasshopper_prefix: str = "/grasshopper",
        rhino_prefix: str = "/rhino",
        io_path: str = "/io",
        solve_path: str = "/solve",
        geometry_query_path: str = "/query_file_geometry",
        layers_path: str = "/layers",
        geometry_details_path: str = "/geometry_details",
        max_upload_bytes: int | None = None,
    ) -> None:
        self.workspace = workspace
        self.base_url = (base_url or os.getenv("MCP_RHINO_COMPUTE_URL") or os.getenv("RHINO_COMPUTE_URL") or "https://localhost:5001").rstrip("/")
        self._enforce_base_url_policy(self.base_url)
        self.api_key = api_key or os.getenv("MCP_RHINO_COMPUTE_KEY") or os.getenv("RHINO_COMPUTE_KEY")
        self.api_key_header = api_key_header
        self.timeout = timeout
        self.max_upload_bytes = self._resolve_max_upload_bytes(max_upload_bytes)
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout, follow_redirects=True)
        self._grasshopper_prefix = self._normalize_prefix(grasshopper_prefix)
        self._rhino_prefix = self._normalize_prefix(rhino_prefix)
        self._io_path = self._normalize_suffix(io_path)
        self._solve_path = self._normalize_suffix(solve_path)
        self._geometry_query_path = self._normalize_suffix(geometry_query_path)
        self._layers_path = self._normalize_suffix(layers_path)
        self._geometry_details_path = self._normalize_suffix(geometry_details_path)
        self._init_capabilities()

    def get_identity(self) -> str:
        return "rhino"

    def get_capabilities(self) -> List[ProviderTool]:
        return self._capabilities

    async def check_health(self) -> Dict[str, Any]:
        response = await self._request_json("GET", "/health")
        return response

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        normalized = name.replace(".", "_")
        if normalized == "rhino_health":
            return await self.check_health()
        if normalized == "rhino_get_definition_io":
            definition_path = self._require_path(arguments, "definition_path", self.SUPPORTED_DEFINITION_EXTENSIONS)
            return await self._definition_io(definition_path)
        if normalized == "rhino_evaluate_definition":
            definition_path = self._require_path(arguments, "definition_path", self.SUPPORTED_DEFINITION_EXTENSIONS)
            input_trees = self._validate_input_trees(arguments.get("input_trees"))
            return await self._evaluate_definition(definition_path, input_trees)
        if normalized == "rhino_query_file_geometry":
            file_path = self._require_path(arguments, "file_path", self.SUPPORTED_GEOMETRY_EXTENSIONS)
            return await self._query_file_geometry(file_path, arguments)
        if normalized == "rhino_get_layers":
            file_path = self._require_path(arguments, "file_path", self.SUPPORTED_GEOMETRY_EXTENSIONS)
            return await self._get_layers(file_path)
        if normalized == "rhino_get_geometry_details":
            file_path = self._require_path(arguments, "file_path", self.SUPPORTED_GEOMETRY_EXTENSIONS)
            return await self._get_geometry_details(file_path, arguments)
        raise ValueError(f"Unknown Rhino tool '{name}'")

    async def shutdown(self) -> None:
        if self._own_client:
            await self._client.aclose()

    def _init_capabilities(self) -> None:
        self._capabilities = [
            ProviderTool(
                name="rhino_health",
                description="Check Rhino.Compute connectivity and service status",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            ProviderTool(
                name="rhino_get_definition_io",
                description="Upload a Grasshopper definition and return its Resthopper input/output metadata",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "definition_path": {
                            "type": "string",
                            "description": "Workspace path to a .gh or .ghx Grasshopper definition",
                        }
                    },
                    "required": ["definition_path"],
                },
            ),
            ProviderTool(
                name="rhino_evaluate_definition",
                description="Upload a Grasshopper definition, solve it against Resthopper-compatible trees, and return the compute response",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "definition_path": {
                            "type": "string",
                            "description": "Workspace path to a .gh or .ghx Grasshopper definition",
                        },
                        "input_trees": {
                            "type": "array",
                            "description": "Resthopper-compatible input trees",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "ParamName": {"type": "string"},
                                    "InnerTree": {"type": "object"},
                                },
                                "required": ["ParamName", "InnerTree"],
                            },
                        },
                    },
                    "required": ["definition_path"],
                },
            ),
            ProviderTool(
                name="rhino_query_file_geometry",
                description="Upload a .3dm file and query geometry summaries through Rhino.Compute",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Workspace path to a .3dm file",
                        },
                        "include_hidden": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include hidden objects when querying geometry",
                        },
                    },
                    "required": ["file_path"],
                },
            ),
            ProviderTool(
                name="rhino_get_layers",
                description="Return layer metadata for a .3dm file through Rhino.Compute",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Workspace path to a .3dm file",
                        }
                    },
                    "required": ["file_path"],
                },
            ),
            ProviderTool(
                name="rhino_get_geometry_details",
                description="Return detailed geometry metadata for a .3dm file through Rhino.Compute",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Workspace path to a .3dm file",
                        }
                    },
                    "required": ["file_path"],
                },
            ),
        ]

    def _normalize_prefix(self, prefix: str) -> str:
        cleaned = prefix.strip()
        if not cleaned:
            return ""
        return "/" + cleaned.strip("/")

    def _normalize_suffix(self, suffix: str) -> str:
        cleaned = suffix.strip()
        if not cleaned:
            return ""
        return "/" + cleaned.strip("/")

    def _build_endpoint(self, prefix: str, suffix: str) -> str:
        if not prefix:
            return suffix or "/"
        if not suffix:
            return prefix
        return f"{prefix}{suffix}"

    def _require_path(self, arguments: Mapping[str, Any], key: str, allowed_extensions: Sequence[str]) -> Path:
        raw_path = arguments.get(key)
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"Argument '{key}' is required.")
        try:
            resolved = self.workspace.assert_in_workspace(Path(raw_path))
        except WorkspaceViolation as exc:
            raise ValueError("Path is outside the allowed workspace.") from exc
        if resolved.suffix.lower() not in {ext.lower() for ext in allowed_extensions}:
            raise ValueError(
                f"Unsupported Rhino file extension '{resolved.suffix or '<none>'}' for '{resolved.name}'."
            )
        if not resolved.exists():
            raise FileNotFoundError(f"Rhino file not found: {resolved.name}")
        return resolved

    def _validate_input_trees(self, input_trees: Any) -> list[dict[str, Any]]:
        if input_trees is None:
            return []
        if not isinstance(input_trees, list):
            raise ValueError("Argument 'input_trees' must be a list when provided.")
        validated: list[dict[str, Any]] = []
        for index, tree in enumerate(input_trees):
            if not isinstance(tree, dict):
                raise ValueError(f"Input tree at index {index} must be an object.")
            if "ParamName" not in tree or "InnerTree" not in tree:
                raise ValueError(f"Input tree at index {index} must include 'ParamName' and 'InnerTree'.")
            validated.append(tree)
        return validated

    def _tree_to_resthopper_values(self, input_trees: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [dict(tree) for tree in input_trees]

    def _file_payload(self, file_path: Path) -> dict[str, Any]:
        self._enforce_upload_size(file_path)
        return {
            "file_name": file_path.name,
            "file_data": base64.b64encode(file_path.read_bytes()).decode("ascii"),
        }

    async def _definition_io(self, definition_path: Path) -> Dict[str, Any]:
        payload = self._file_payload(definition_path)
        response = await self._request_json(
            "POST",
            self._build_endpoint(self._grasshopper_prefix, self._io_path),
            payload=payload,
        )
        return response

    async def _evaluate_definition(self, definition_path: Path, input_trees: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        io_response = await self._definition_io(definition_path)
        definition_id = (
            io_response.get("definition_id")
            or io_response.get("id")
            or io_response.get("DefinitionId")
            or io_response.get("DefinitionID")
        )
        if not definition_id:
            raise BridgeError("Rhino.Compute did not return a definition identifier from the IO endpoint.")

        solve_payload = {
            "definition_id": definition_id,
            "input_trees": self._tree_to_resthopper_values(input_trees),
        }
        return await self._request_json(
            "POST",
            self._build_endpoint(self._grasshopper_prefix, self._solve_path),
            payload=solve_payload,
        )

    async def _query_file_geometry(self, file_path: Path, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        payload = self._file_payload(file_path)
        payload["include_hidden"] = bool(arguments.get("include_hidden", False))
        return await self._request_json(
            "POST",
            self._build_endpoint(self._rhino_prefix, self._geometry_query_path),
            payload=payload,
        )

    async def _get_layers(self, file_path: Path) -> Dict[str, Any]:
        payload = self._file_payload(file_path)
        return await self._request_json(
            "POST",
            self._build_endpoint(self._rhino_prefix, self._layers_path),
            payload=payload,
        )

    async def _get_geometry_details(self, file_path: Path, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        payload = self._file_payload(file_path)
        if "object_ids" in arguments:
            payload["object_ids"] = arguments["object_ids"]
        return await self._request_json(
            "POST",
            self._build_endpoint(self._rhino_prefix, self._geometry_details_path),
            payload=payload,
        )

    async def _request_json(self, method: str, endpoint: str, *, payload: dict[str, Any] | None = None) -> Dict[str, Any]:
        headers = {}
        if self.api_key:
            headers[self.api_key_header] = self.api_key
        try:
            response = await self._client.request(method, endpoint, json=payload, headers=headers)
            response.raise_for_status()
            response_payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise BridgeError(f"Rhino.Compute request to {endpoint} failed with status {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise BridgeError(f"Rhino.Compute request to {endpoint} failed: {exc.__class__.__name__}") from exc
        except ValueError as exc:
            raise BridgeError(f"Rhino.Compute response from {endpoint} was not valid JSON") from exc
        if not isinstance(response_payload, dict):
            raise BridgeError(f"Rhino.Compute response from {endpoint} was not a JSON object")
        return response_payload

    def _enforce_upload_size(self, file_path: Path) -> None:
        if file_path.stat().st_size > self.max_upload_bytes:
            raise ValueError(
                f"Rhino file '{file_path.name}' exceeds the maximum upload size of {self.max_upload_bytes} bytes."
            )

    def _enforce_base_url_policy(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Rhino.Compute base URL must use http or https.")
        if parsed.scheme == "http" and not self._is_loopback_host(parsed.hostname):
            raise ValueError("Rhino.Compute base URL must use https unless the host is localhost or 127.0.0.1.")

    def _is_loopback_host(self, hostname: str | None) -> bool:
        return hostname in {"localhost", "127.0.0.1", "::1"}

    def _resolve_max_upload_bytes(self, max_upload_bytes: int | None) -> int:
        if max_upload_bytes is not None:
            return int(max_upload_bytes)
        env_value = os.getenv("MCP_RHINO_COMPUTE_MAX_UPLOAD_BYTES") or os.getenv("RHINO_COMPUTE_MAX_UPLOAD_BYTES")
        if env_value:
            return int(env_value)
        return 50 * 1024 * 1024
