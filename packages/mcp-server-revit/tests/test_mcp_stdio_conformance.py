"""Protocol conformance checks against the real server in mock mode.

A fresh interpreter starts ``python -m revit_mcp_server.mcp_server`` over stdio and
the installed MCP SDK client talks to it, so a regression in initialize, the list
calls, a tool call or the error replies shows up as a client would see it. No
Revit, no network and no secrets are needed. CI runs this file with the rest of
the suite on every pull request.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
jsonschema = pytest.importorskip("jsonschema")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from mcp.shared.exceptions import McpError  # noqa: E402

pytestmark = [pytest.mark.anyio, pytest.mark.timeout(120)]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _server_params(tmp_path: Path) -> StdioServerParameters:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("MCP_REVIT_")}
    env.update(
        {
            "MCP_REVIT_MODE": "mock",
            "MCP_REVIT_WORKSPACE_DIR": str(workspace),
            "MCP_REVIT_ALLOWED_DIRECTORIES": str(workspace),
            "MCP_REVIT_AUDIT_LOG": str(tmp_path / "audit.log"),
        }
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "revit_mcp_server.mcp_server"],
        env=env,
        cwd=str(tmp_path),
    )


async def test_protocol_conformance_in_mock_mode(tmp_path: Path) -> None:
    async with stdio_client(_server_params(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            # initialize
            init = await session.initialize()
            assert init.serverInfo.name == "aec-model-bridge"
            assert init.protocolVersion
            caps = init.capabilities
            assert caps.tools is not None
            assert caps.prompts is not None
            assert caps.resources is not None

            await session.send_ping()

            # tools/list
            tools = (await session.list_tools()).tools
            assert tools
            names = [t.name for t in tools]
            assert len(names) == len(set(names)), "duplicate tool names"
            for tool in tools:
                assert tool.name.strip() and tool.name == tool.name.strip()
                assert tool.annotations is not None, f"{tool.name} has no annotations"
                assert isinstance(tool.annotations.readOnlyHint, bool), tool.name
                schema = tool.inputSchema
                assert isinstance(schema, dict) and schema.get("type") == "object", (
                    tool.name
                )
                try:
                    jsonschema.Draft202012Validator.check_schema(schema)
                except jsonschema.SchemaError as exc:  # pragma: no cover - failure path
                    pytest.fail(
                        f"{tool.name} has an invalid inputSchema: {exc.message}"
                    )
                if tool.outputSchema is not None:
                    jsonschema.Draft202012Validator.check_schema(tool.outputSchema)

            # prompts/list and prompts/get
            prompts = (await session.list_prompts()).prompts
            assert prompts
            prompt_names = [p.name for p in prompts]
            assert len(prompt_names) == len(set(prompt_names)), "duplicate prompt names"
            assert all(p.description for p in prompts)
            with pytest.raises(McpError):
                await session.get_prompt("no_such_prompt_name", None)

            # resources/list, resources/templates/list and resources/read
            resources = (await session.list_resources()).resources
            assert resources
            uris = [str(r.uri) for r in resources]
            assert len(uris) == len(set(uris)), "duplicate resource uris"
            templates = (await session.list_resource_templates()).resourceTemplates
            assert templates
            assert all("{" in t.uriTemplate for t in templates)
            read_result = await session.read_resource("aec://plans/pending")
            assert read_result.contents
            json.loads(read_result.contents[0].text)
            with pytest.raises(McpError):
                await session.read_resource("aec://no-such-resource/x")

            # tools/call: one read-only tool, then the two error shapes
            health = await session.call_tool("revit_health", {})
            assert not health.isError
            assert health.content
            assert health.content[0].type == "text"
            unknown = await session.call_tool("no_such_tool_name", {})
            assert unknown.isError
            bad_args = await session.call_tool("revit_health", {"unexpected": [1, 2]})
            # A malformed call is answered, never a crash: the session still works.
            assert bad_args.content is not None
            await session.send_ping()
