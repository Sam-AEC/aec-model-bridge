"""
MCP Server for AEC - Dynamic multi-provider automation server.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .errors import BridgeError
from .registry_factory import build_registry
from .security.audit import redact_data

logger = logging.getLogger(__name__)

# Initialize the MCP server
app = Server("aec-model-bridge")

# Build the registry used by the stdio MCP server below.
registry, approval_provider, job_manager, module_registry, workspace = build_registry()


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available AEC tools from registered providers."""
    return [
        Tool(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema
        )
        for t in registry.get_all_tools()
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Execute a registered AEC tool."""
    provider = registry.lookup_tool_provider(name)
    if not provider:
        return [TextContent(
            type="text",
            text=f"Error: Unknown tool '{name}'"
        )]

    # Approval Gate Middleware Check
    tool_def = registry.lookup_tool(name)
    if tool_def and tool_def.is_mutating:
        try:
            approval_provider.gate.check_tool_execution(name, arguments)
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Approval Gate Blocked: {str(e)}"
            )]

    try:
        # Check if deferred execution is requested.
        run_async = False
        idempotency_key = None
        if isinstance(arguments, dict):
            args_copy = dict(arguments)
            run_async = args_copy.pop("run_async", False)
            if isinstance(run_async, str):
                run_async = run_async.lower() in ("true", "1", "yes")
            run_async = bool(run_async)
            idempotency_key = args_copy.get("idempotency_key")

        if run_async:
            async def run_tool_job(context=None):
                return await provider.execute_tool(name, arguments)

            job_ref = await job_manager.submit(
                run_tool_job,
                idempotency_key=idempotency_key
            )
            response_text = f"✓ Job {job_ref.job_id} queued successfully\n\n"
            response_text += f"Result:\n{json.dumps(job_ref.to_dict(), indent=2)}"
            return [TextContent(type="text", text=response_text)]

        # Execute the tool on the provider
        result = await provider.execute_tool(name, arguments)
        
        # If mutating tool and plan_id is provided, transition state to executed
        if tool_def and tool_def.is_mutating and isinstance(arguments, dict) and "plan_id" in arguments:
            plan_id = arguments["plan_id"]
            try:
                approval_provider.gate.update_plan_state(plan_id, "executed")
            except Exception:
                pass

        redacted_result = redact_data(result)

        # Format the response
        response_text = f"✓ {name} executed successfully\n\n"
        response_text += f"Result:\n{json.dumps(redacted_result, indent=2)}"

        return [TextContent(type="text", text=response_text)]

    except BridgeError as e:
        error_msg = f"Revit Bridge Error: {redact_data(str(e))}\n\n"
        error_msg += "Make sure:\n"
        error_msg += "1. Revit is running\n"
        error_msg += "2. A project is open in Revit\n"
        error_msg += "3. The AEC Model Bridge add-in is loaded\n"
        error_msg += "4. The bridge is accessible at http://localhost:3000"

        return [TextContent(type="text", text=error_msg)]

    except Exception as e:
        return [TextContent(
            type="text",
            text=f"Error: {redact_data(str(e))}"
        )]

async def main():
    """Run the MCP server."""
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    finally:
        await job_manager.shutdown(cancel_running=True)

def run_mcp_server():
    """Entry point for running the MCP server."""
    asyncio.run(main())


if __name__ == "__main__":
    run_mcp_server()
