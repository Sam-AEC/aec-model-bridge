"""
MCP Server for AEC - Dynamic multi-provider automation server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .config import config
from .errors import BridgeError
from .providers import (
    ProviderRegistry,
    RevitProvider,
    IfcProvider,
    AECMapperProvider,
    RhinoProvider,
    SemanticGraphProvider,
    SpeckleProvider,
    AutodeskDataProvider,
    JobProvider,
    SQLiteExporterProvider,
    McpProxyProvider,
    NavisworksProvider,
    ApprovalProvider,
    ModuleProvider,
    SemanticProvider,
)
from .module_registry import ModuleRegistry
from .security.workspace import WorkspaceMonitor
from .security.audit import redact_data
from .jobs import JobManager

logger = logging.getLogger(__name__)

# Initialize the MCP server
app = Server("aec-model-bridge")

# Create workspace monitor
workspace = WorkspaceMonitor(config.allowed_directories)

# Initialize registry and register providers
registry = ProviderRegistry()
approval_provider = ApprovalProvider(workspace=workspace, registry=registry)
registry.register(approval_provider)
registry.register(RevitProvider(workspace=workspace))
registry.register(IfcProvider(workspace=workspace))
registry.register(AECMapperProvider(workspace=workspace))
registry.register(SQLiteExporterProvider(workspace=workspace, registry=registry))
registry.register(NavisworksProvider(workspace=workspace))
registry.register(SemanticProvider(workspace=workspace, registry=registry))

# Initialize and register Module registry and Module provider
module_registry = ModuleRegistry(config_obj=config)
module_registry.discover_and_load()
registry.register(ModuleProvider(module_registry=module_registry, workspace=workspace))

# Initialize Job Manager and Job Provider
job_manager = JobManager()
registry.register(JobProvider(manager=job_manager))

# Rhino Provider
try:
    registry.register(RhinoProvider(workspace=workspace))
except Exception as e:
    logger.warning("Could not initialize RhinoProvider: %s", e)

# Semantic Graph Provider
try:
    registry.register(SemanticGraphProvider())
except Exception as e:
    logger.warning("Could not initialize SemanticGraphProvider: %s", e)

# Speckle Provider
try:
    registry.register(SpeckleProvider())
except Exception as e:
    logger.warning("Could not initialize SpeckleProvider: %s. Please set SPECKLE_CLIENT_ID.", e)

# Autodesk Data Provider
try:
    registry.register(AutodeskDataProvider())
except Exception as e:
    logger.warning("Could not initialize AutodeskDataProvider: %s. Please set APS_CLIENT_ID.", e)

# Mcp Proxy Providers
proxy_targets = os.getenv("MCP_PROXY_TARGETS")
if proxy_targets:
    for target in proxy_targets.split(","):
        target = target.strip()
        if not target:
            continue
        if "=" in target:
            name, url = target.split("=", 1)
            name = name.strip()
            url = url.strip()
            identity = f"proxy_{name}"
        else:
            url = target
            identity = "proxy"
        
        try:
            registry.register(McpProxyProvider(target_url=url, identity=identity))
        except Exception as e:
            logger.warning("Could not initialize McpProxyProvider for %s: %s", target, e)

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
