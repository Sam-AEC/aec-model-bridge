from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revit_mcp_server.providers.cloud import (
    AutodeskDataProvider,
    OAuthTokenBundle,
    SpeckleProvider,
)


def _json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


@pytest.mark.anyio
async def test_speckle_oauth_pkce_exchange_and_state_validation() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        assert request.url == httpx.URL("https://speckle.example/auth/token")
        form = parse_qs(request.content.decode("utf-8"))
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["oauth-code-123"]
        assert form["code_verifier"][0]
        assert "client_id" not in form
        assert request.headers["Authorization"].startswith("Basic ")
        return _json_response(
            {
                "access_token": "speckle-access-token",
                "refresh_token": "speckle-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "profile:read streams:read",
            }
        )

    provider = SpeckleProvider(
        host="https://speckle.example",
        client_id="speckle-client",
        client_secret="speckle-secret",
        redirect_uri="http://localhost/callback",
        allow_localhost_http=True,
        oauth_transport=httpx.MockTransport(handler),
        oauth_pending_state_ttl_seconds=1,
        oauth_max_pending_states=2,
    )

    start = await provider.execute_tool("speckle.oauth_start", {})
    parsed = urlparse(start["authorization_url"])
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert params["response_type"] == ["code"]
    assert start["state"] == params["state"][0]
    assert params["code_challenge_method"] == ["S256"]
    assert "code_challenge" in params

    exchanged = await provider.execute_tool(
        "speckle_oauth_exchange_code",
        {"code": "oauth-code-123", "state": start["state"]},
    )
    assert exchanged["authorized"] is True
    assert exchanged["has_refresh_token"] is True
    assert "access_token" not in exchanged
    assert len(seen_requests) == 1

    status = await provider.execute_tool("speckle_auth_status", {})
    assert status["authorized"] is True

    with pytest.raises(ValueError, match="OAuth state validation failed"):
        await provider.execute_tool(
            "speckle_oauth_exchange_code",
            {"code": "oauth-code-123", "state": "wrong-state"},
        )

    await provider.shutdown()


@pytest.mark.anyio
async def test_oauth_pending_state_ttl_pruning_and_bounded_count() -> None:
    provider = AutodeskDataProvider(
        client_id="aps-client",
        client_secret="aps-secret",
        redirect_uri="http://localhost/callback",
        allow_localhost_http=True,
        oauth_pending_state_ttl_seconds=3600,
        oauth_max_pending_states=2,
    )

    start_one = await provider.execute_tool("autodesk_data_oauth_start", {})
    start_two = await provider.execute_tool("autodesk_data_oauth_start", {})
    assert start_one["state"] != start_two["state"]

    with pytest.raises(ValueError, match="Too many pending OAuth states"):
        await provider.execute_tool("autodesk_data_oauth_start", {})

    for pending in provider.oauth._pending_states.values():
        pending.created_at = 0

    start_three = await provider.execute_tool("autodesk_data_oauth_start", {})
    assert start_three["state"]
    assert len(provider.oauth._pending_states) == 1

    await provider.shutdown()


@pytest.mark.anyio
async def test_autodesk_refresh_uses_callback_credentials_and_no_tool_token_args() -> None:
    seen_requests: list[httpx.Request] = []

    async def credential_callback(name: str) -> str | None:
        if name == "client_secret":
            return "aps-secret"
        if name == "refresh_token":
            return "callback-refresh-token"
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        form = parse_qs(request.content.decode("utf-8"))
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["callback-refresh-token"]
        assert "client_id" not in form
        assert request.headers["Authorization"].startswith("Basic ")
        return _json_response(
            {
                "access_token": "aps-access-token",
                "refresh_token": "aps-refresh-token",
                "expires_in": 1800,
                "token_type": "Bearer",
                "scope": "data:read data:write",
            }
        )

    provider = AutodeskDataProvider(
        client_id="aps-client",
        redirect_uri="http://localhost/callback",
        allow_localhost_http=True,
        credential_callback=credential_callback,
        oauth_transport=httpx.MockTransport(handler),
    )

    refreshed = await provider.execute_tool("autodesk_data_oauth_refresh", {})
    assert refreshed["authorized"] is True
    assert refreshed["has_refresh_token"] is True
    assert len(seen_requests) == 1

    await provider.shutdown()


@pytest.mark.anyio
async def test_speckle_graphql_calls_auth_headers_idempotency_and_merge_configuration() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        assert request.headers["Authorization"] == "Bearer token-123"
        payload = request.read().decode("utf-8")
        if "SpeckleProjects" in payload:
            return _json_response({"data": {"activeUser": {"projects": {"items": [{"id": "p1", "name": "Project 1"}]}}}})
        if "SpeckleCreateModel" in payload:
            assert request.headers["Idempotency-Key"] == "idem-001"
            return _json_response({"data": {"projectMutations": {"modelCreate": {"id": "m1", "name": "Model 1", "description": None}}}})
        if "ConfiguredSpeckleMerge" in payload:
            return _json_response({"data": {"customMerge": {"ok": True}}})
        raise AssertionError(payload)

    provider_without_merge = SpeckleProvider(
        host="https://speckle.example",
        client_id="speckle-client",
        client_secret="speckle-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    provider_without_merge.oauth._token_bundle = OAuthTokenBundle(access_token="token-123", refresh_token="refresh-123")

    listed = await provider_without_merge.execute_tool("speckle_list_projects", {"limit": 10})
    assert listed["projects"][0]["id"] == "p1"

    created = await provider_without_merge.execute_tool(
        "speckle_create_model",
        {"project_id": "p1", "name": "Model 1", "idempotency_key": "idem-001"},
    )
    assert created["model"]["id"] == "m1"

    request_count_before_merge = len(seen_requests)
    with pytest.raises(NotImplementedError, match="merge_operation_builder"):
        await provider_without_merge.execute_tool(
            "speckle_merge_model",
            {
                "project_id": "p1",
                "source_model_id": "m-source",
                "target_model_id": "m-target",
                "message": "merge now",
            },
        )
    assert len(seen_requests) == request_count_before_merge
    await provider_without_merge.shutdown()

    def merge_builder(arguments: dict) -> dict:
        return {
            "query": """
            mutation ConfiguredSpeckleMerge($projectId:String!, $source:String!, $target:String!, $message:String!) {
              customMerge(projectId:$projectId, source:$source, target:$target, message:$message) { ok }
            }
            """,
            "variables": {
                "projectId": arguments["project_id"],
                "source": arguments["source_model_id"],
                "target": arguments["target_model_id"],
                "message": arguments["message"],
            },
            "result_path": ["customMerge", "ok"],
        }

    provider_with_merge = SpeckleProvider(
        host="https://speckle.example",
        client_id="speckle-client",
        client_secret="speckle-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        merge_operation_builder=merge_builder,
    )
    provider_with_merge.oauth._token_bundle = OAuthTokenBundle(access_token="token-123", refresh_token="refresh-123")

    merged = await provider_with_merge.execute_tool(
        "speckle_merge_branch",
        {
            "project_id": "p1",
            "source_model_id": "m-source",
            "target_model_id": "m-target",
            "message": "merge now",
        },
    )
    assert merged["merged"] is True

    assert len(seen_requests) == 3
    await provider_with_merge.shutdown()


@pytest.mark.anyio
async def test_autodesk_rest_calls_bcf_validation_idempotency_and_redaction() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        assert request.headers["Authorization"] == "Bearer aps-token"
        if request.method == "GET" and request.url.path == "/project/v1/hubs":
            return _json_response({"data": [{"id": "hub-1"}]})
        if request.method == "GET" and str(request.url).endswith("/data/v1/projects/project%2F1/versions/version%201"):
            return _json_response({"data": {"id": "version-1", "type": "versions"}})
        if request.method == "POST" and request.url.path == "/issues/v1/topics":
            assert request.headers["Idempotency-Key"] == "topic-001"
            return _json_response(
                {
                    "topicId": "topic-1",
                    "Authorization": "should-not-leak",
                    "access_token": "should-not-leak",
                    "snapshot": r"C:\Users\sammo\secret.png",
                }
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    provider = AutodeskDataProvider(
        client_id="aps-client",
        client_secret="aps-secret",
        issues_endpoint="https://developer.api.autodesk.com/issues/v1/topics",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    provider.oauth._token_bundle = OAuthTokenBundle(access_token="aps-token", refresh_token="refresh-token")

    hubs = await provider.execute_tool("autodesk_data_list_hubs", {})
    assert hubs["hubs"][0]["id"] == "hub-1"

    version = await provider.execute_tool(
        "autodesk_data_get_version_metadata",
        {"project_id": "project/1", "version_id": "version 1"},
    )
    assert version["version"]["id"] == "version-1"

    created = await provider.execute_tool(
        "autodesk_data_create_topic",
        {
            "container_id": "container-1",
            "title": "Coordination issue",
            "description": "Beam clashes with duct",
            "status": "open",
            "type": "issue",
            "ifc_guid_refs": ["0J$w1A2B3C4D5E6F7G8H9I"],
            "viewpoint": {"guid": "view-1", "snapshot_url": "https://example.com/view.png", "index": 0},
            "idempotency_key": "topic-001",
        },
    )
    assert created["topicId"] == "topic-1"
    assert created["Authorization"] == "<redacted>"
    assert created["access_token"] == "<redacted>"
    assert created["snapshot"] == "<redacted-path>"

    with pytest.raises(ValueError, match="Invalid IFC GUID reference"):
        await provider.execute_tool(
            "autodesk_data_create_topic",
            {
                "container_id": "container-1",
                "title": "Bad issue",
                "description": "Bad guid",
                "ifc_guid_refs": ["not-a-guid"],
            },
        )

    items_seen: list[httpx.Request] = []

    def item_handler(request: httpx.Request) -> httpx.Response:
        items_seen.append(request)
        assert str(request.url).endswith("/data/v1/projects/project%2F1/folders/folder%201%2Fchild/contents")
        return _json_response({"data": []})

    item_provider = AutodeskDataProvider(
        client_id="aps-client",
        client_secret="aps-secret",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(item_handler)),
    )
    item_provider.oauth._token_bundle = OAuthTokenBundle(access_token="aps-token", refresh_token="refresh-token")
    await item_provider.execute_tool(
        "autodesk_data_list_items",
        {"project_id": "project/1", "folder_id": "folder 1/child"},
    )
    assert len(items_seen) == 1

    await item_provider.shutdown()
    await provider.shutdown()


@pytest.mark.anyio
async def test_redaction_in_errors_and_https_enforcement() -> None:
    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, json={"error": "failed"})

    provider = AutodeskDataProvider(
        client_id="aps-client",
        client_secret="aps-secret",
        issues_endpoint="https://developer.api.autodesk.com/issues/v1/topics",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(failing_handler)),
    )
    provider.oauth._token_bundle = OAuthTokenBundle(access_token="aps-token", refresh_token="refresh-token")

    with pytest.raises(RuntimeError) as exc:
        await provider.execute_tool(
            "autodesk_data_create_topic",
            {
                "container_id": "container-1",
                "title": "Broken issue",
                "description": "Payload should fail cleanly",
                "viewpoint": {"snapshot_url": "failed at C:\\Users\\sammo\\Desktop\\secret.png and /Users/sammo/private/file.bcfv"},
            },
        )

    assert r"C:\Users\sammo\Desktop\secret.png" not in str(exc.value)
    assert "/Users/sammo/private/file.bcfv" not in str(exc.value)
    assert "<redacted-path>" in str(exc.value)

    with pytest.raises(ValueError, match="must use HTTPS"):
        SpeckleProvider(
            host="http://speckle.example",
            client_id="speckle-client",
            client_secret="speckle-secret",
        )

    localhost_provider = SpeckleProvider(
        host="https://speckle.example",
        client_id="speckle-client",
        client_secret="speckle-secret",
        redirect_uri="http://localhost/callback",
        allow_localhost_http=True,
    )
    await localhost_provider.shutdown()
    await provider.shutdown()
