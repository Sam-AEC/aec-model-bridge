from __future__ import annotations

import base64
import json

import httpx
import pytest

from revit_mcp_server.providers.rhino import RhinoProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor


def _write_sample_file(path, content=b"sample"):
    path.write_bytes(content)
    return path


def test_rhino_capabilities_are_present(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example")

    names = [tool.name for tool in provider.get_capabilities()]
    assert names == [
        "rhino_health",
        "rhino_get_definition_io",
        "rhino_evaluate_definition",
        "rhino_query_file_geometry",
        "rhino_get_layers",
        "rhino_get_geometry_details",
    ]

    schema_dump = json.dumps([tool.model_dump(by_alias=True) for tool in provider.get_capabilities()])
    assert "RHINO_COMPUTE_KEY" not in schema_dump
    assert "MCP_RHINO_COMPUTE_KEY" not in schema_dump


@pytest.mark.anyio
async def test_rhino_health_uses_injected_client_and_official_header(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    seen = {}
    secret = "super-secret-token"

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("RhinoComputeKey")
        return httpx.Response(200, json={"status": "healthy", "service": "rhino"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://compute.example")
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example", api_key=secret, client=client)

    response = await provider.check_health()
    assert response["status"] == "healthy"
    assert seen == {"method": "GET", "path": "/health", "auth": secret}

    await provider.shutdown()
    await client.aclose()


@pytest.mark.anyio
async def test_rhino_get_definition_io_validates_workspace_and_payload(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    definition_path = _write_sample_file(tmp_path / "function.gh", b"gh-bytes")
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("RhinoComputeKey")
        seen["has_x_api_key"] = "X-Api-Key" in request.headers
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"definition_id": "def-123", "inputs": [], "outputs": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://compute.example")
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example", api_key="secret", client=client)

    response = await provider.execute_tool("rhino_get_definition_io", {"definition_path": str(definition_path)})
    assert response["definition_id"] == "def-123"
    assert seen["path"] == "/grasshopper/io"
    assert seen["auth"] == "secret"
    assert seen["has_x_api_key"] is False
    assert seen["payload"]["file_name"] == "function.gh"
    assert seen["payload"]["file_data"] == base64.b64encode(b"gh-bytes").decode("ascii")
    assert set(seen["payload"]) == {"file_name", "file_data"}

    await provider.shutdown()
    await client.aclose()


@pytest.mark.anyio
async def test_rhino_evaluate_definition_posts_io_then_solve(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    definition_path = _write_sample_file(tmp_path / "function.ghx", b"ghx-bytes")
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, json.loads(request.content.decode("utf-8"))))
        if request.url.path.endswith("/io"):
            return httpx.Response(200, json={"id": "definition-777"})
        return httpx.Response(200, json={"values": [{"ParamName": "A", "InnerTree": {}}], "errors": [], "warnings": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://compute.example")
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example", client=client)

    result = await provider.execute_tool(
        "rhino_evaluate_definition",
        {
            "definition_path": str(definition_path),
            "input_trees": [
                {"ParamName": "X", "InnerTree": {"{0}": [{"type": "System.Double", "data": "1.0"}]}}
            ],
        },
    )

    assert result["values"][0]["ParamName"] == "A"
    assert [item[1] for item in requests] == ["/grasshopper/io", "/grasshopper/solve"]
    assert requests[1][2]["definition_id"] == "definition-777"
    assert requests[1][2]["input_trees"][0]["ParamName"] == "X"
    assert "definition_path" not in requests[1][2]

    await provider.shutdown()
    await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_name,filename,expected_path",
    [
        ("rhino_query_file_geometry", "model.3dm", "/rhino/query_file_geometry"),
        ("rhino_get_layers", "model.3dm", "/rhino/layers"),
        ("rhino_get_geometry_details", "model.3dm", "/rhino/geometry_details"),
    ],
)
async def test_rhino_3dm_tools_validate_extensions_and_use_expected_paths(tmp_path, tool_name, filename, expected_path):
    workspace = WorkspaceMonitor([tmp_path])
    file_path = _write_sample_file(tmp_path / filename, b"3dm-bytes")
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("RhinoComputeKey")
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "ok", "tool": tool_name})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://compute.example")
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example", client=client)

    result = await provider.execute_tool(tool_name, {"file_path": str(file_path), "include_hidden": True, "object_ids": [1, 2]})
    assert result["tool"] == tool_name
    assert seen["path"] == expected_path
    assert seen["auth"] is None
    assert seen["payload"]["file_name"] == "model.3dm"
    assert "file_path" not in seen["payload"]
    assert set(seen["payload"]).issuperset({"file_name", "file_data"})

    await provider.shutdown()
    await client.aclose()


@pytest.mark.anyio
async def test_rhino_rejects_unsupported_extensions_before_request(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    file_path = _write_sample_file(tmp_path / "unsupported.txt")
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example")

    with pytest.raises(ValueError, match="Unsupported Rhino file extension"):
        await provider.execute_tool("rhino_get_definition_io", {"definition_path": str(file_path)})

    await provider.shutdown()


@pytest.mark.anyio
async def test_rhino_redacts_secret_from_error_messages(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://compute.example")
    provider = RhinoProvider(
        workspace=workspace,
        base_url="https://compute.example",
        api_key="top-secret-token",
        client=client,
    )

    with pytest.raises(Exception) as exc:
        await provider.check_health()

    assert "top-secret-token" not in str(exc.value)
    assert "RhinoComputeKey" not in str(exc.value)

    await provider.shutdown()
    await client.aclose()


def test_rhino_rejects_non_loopback_http_base_url(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])

    with pytest.raises(ValueError, match="must use https unless the host is localhost or 127.0.0.1"):
        RhinoProvider(workspace=workspace, base_url="http://compute.example")


def test_rhino_allows_localhost_http_base_url(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RhinoProvider(workspace=workspace, base_url="http://127.0.0.1:5001")
    assert provider.base_url == "http://127.0.0.1:5001"


@pytest.mark.anyio
async def test_rhino_rejects_oversized_uploads_before_read(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    definition_path = _write_sample_file(tmp_path / "huge.gh", b"x" * 16)
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example", max_upload_bytes=8)

    with pytest.raises(ValueError, match="exceeds the maximum upload size"):
        await provider.execute_tool("rhino_get_definition_io", {"definition_path": str(definition_path)})

    await provider.shutdown()


@pytest.mark.anyio
async def test_rhino_workspace_errors_do_not_expose_absolute_paths(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    outside_dir = tmp_path.parent / "outside"
    outside_dir.mkdir(exist_ok=True)
    file_path = _write_sample_file(outside_dir / "escape.gh")
    provider = RhinoProvider(workspace=workspace, base_url="https://compute.example")

    with pytest.raises(ValueError, match="outside the allowed workspace"):
        await provider.execute_tool("rhino_get_definition_io", {"definition_path": str(file_path)})

    await provider.shutdown()
