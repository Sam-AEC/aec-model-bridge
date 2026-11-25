"""
MCP Server for AEC - Dynamic multi-provider automation server.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import (
    CallToolResult, CreateTaskResult, GetPromptResult, Prompt, Resource, ResourceLink, ResourceTemplate, Tool,
    TextContent,
)

from . import mcp_prompts, mcp_resources, mcp_tasks

from .elicitation import (
    MAX_ROUNDS, ElicitationForbidden, InputNeeded, elicit_choice, elicitation_allowed, missing_export_path,
)
from .errors import BridgeError, CommandFailed
from .registry_factory import build_registry
from .security.approval import HUMAN_ONLY_TOOLS
from .security.dispatch import (
    gate_after, gate_after_result, gate_before, result_failed, settle_in_flight,
)
from .security.gating import requires_approval
from .security.audit import redact_data as _redact_secrets
from .security.response_redaction import redact_response
from .security.module_execution import authorized_module_execution
from .output_schemas import output_schema_for, structured_for
from .tool_metadata import enrich_tool, is_read_only_tool
from .read_cursor import Context as CursorContext, CursorError, binding as cursor_binding
from .result_presentation import next_page, result_json, split_response_options
from .tool_profiles import ToolProfileBlocked, load_tool_profile

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = (
    "AEC Model Bridge exposes Autodesk Revit (and Navisworks, Rhino, IFC, Speckle) as MCP tools. "
    "Read-only tools run immediately. Every tool that changes a model requires an approved plan: "
    "call plan_actions with the proposed changes, then STOP and ask the person to review and approve the plan "
    "themselves, in the Revit panel's Plans view or with the command-line tool `aec-model-bridge-approve`. "
    "You cannot approve, reject or roll back a plan, and must not try to work around that. "
    "Only after the person tells you the plan is approved, call execute_plan (or pass the plan_id to the write tool "
    "with exactly the arguments that were approved; an approved action runs once). "
    "Before the first change in a task, call revit_get_context once and read server.plans_required: "
    "false (Dev mode or Auto) means call write tools directly, with no plan_actions and no plan_id; "
    "true means the plan steps above apply. The person can switch modes at any time, so check again after a refusal. "
    "Revit lengths are in feet. "
    "A read answer with truncated: true and a cursor continues with the same call plus response_options.cursor. "
    "In MCP_REVIT_MODE=mock the server returns canned responses and needs no Revit.\n"
    "Tool families: revit_* Revit reads, checks, parameters and views; qaqc_checker_*, naming_checker_*, *_audit QA; "
    "snapshot_* and model_* snapshots, diffs and inspection.\n"
    "More families: selection_tools_*, recipe_*, report_*, rhino_*, speckle_*, navisworks_*, ifc_*.\n"
    "A tool missing from your list is hidden by the startup profile (MCP_REVIT_TOOL_PROFILE: core, daily or full) "
    "and calls to it are refused; ask the person to switch profile and restart."
)


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("aec-model-bridge")
    except Exception:
        return "0.0.0"


def _make_server() -> Server:
    # Report this package's version (not the MCP SDK's) and, where the installed
    # SDK supports them, the usage instructions and website.
    wanted = {
        "version": _package_version(),
        "instructions": SERVER_INSTRUCTIONS,
        "website_url": "https://github.com/Sam-AEC/aec-model-bridge",
    }
    accepted = inspect.signature(Server.__init__).parameters
    return Server("aec-model-bridge", **{k: v for k, v in wanted.items() if k in accepted})


# Initialize the MCP server
app = _make_server()

# Registry components — populated in main() so importing this module never
# triggers provider construction (Rhino health probes, Speckle OAuth, SQLite
# connections, module filesystem scans) as a side effect.
registry = None
approval_provider = None
job_manager = None
workspace_monitor = None

# MCP Tasks (see mcp_tasks.py and docs/mcp-tasks.md): task-augmented tools/call for
# long tools, backed by job_manager. Clients that send no `task` field are unaffected.
task_bridge = mcp_tasks.TaskBridge(lambda: job_manager)
TASKS_ENABLED = mcp_tasks.register_task_handlers(app, task_bridge)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available AEC tools from registered providers."""
    # enrich_tool adds parameter docs and behaviour annotations (readOnlyHint,
    # destructiveHint, idempotentHint, openWorldHint) without changing behaviour.
    # For MCP Tasks it also sets execution.taskSupport on mcp_tasks.TASK_TOOLS.
    return [
        enrich_tool(provider.get_identity(), t)
        for provider, t in registry.get_tools_with_providers()
        if t.name not in HUMAN_ONLY_TOOLS
    ]

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    return mcp_prompts.list_prompts()


@app.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    return mcp_prompts.get_prompt(name, arguments)


@app.list_resources()
async def list_resources() -> list[Resource]:
    return mcp_resources.list_resources()


@app.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return mcp_resources.list_resource_templates()


@app.read_resource()
async def read_resource(uri: Any) -> list[ReadResourceContents]:
    """Read-only workspace resources. Ids are validated and results redacted in mcp_resources."""
    text = mcp_resources.read_resource(
        uri, workspace_monitor.allowed_directories[0], approval_provider.gate,
    )
    return [ReadResourceContents(content=text, mime_type=mcp_resources.MIME)]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent] | CallToolResult | CreateTaskResult:
    """Execute a registered AEC tool.

    When a tool needs one more input (InputNeeded) and the client declared elicitation,
    the person is asked once per missing input and the call runs again with the answer.
    Otherwise, or on decline, cancel or timeout, the call ends with the plain refusal.
    Approval tools never ask (elicitation.elicitation_allowed).
    """
    rounds = 0
    while True:
        try:
            return await _call_tool_once(name, arguments)
        except InputNeeded as need:
            answer = None
            if rounds < MAX_ROUNDS and _may_elicit(name, arguments):
                try:
                    answer = await elicit_choice(
                        _client_session(), need.question, need.options, tool=name, field=need.field,
                        title=need.title, related_request_id=_request_id(),
                    )
                except ElicitationForbidden:
                    answer = None
            if answer is None:
                return _tool_error("input_needed", need.refusal)
            try:
                arguments = need.apply(arguments if isinstance(arguments, dict) else {}, answer)
            except InputNeeded as again:
                return _tool_error("input_needed", again.refusal)
            rounds += 1


def _client_session() -> Any:
    """The MCP session of the current request, or None outside a request (direct calls in tests)."""
    try:
        return app.request_context.session
    except LookupError:
        return None


def _request_id() -> Any:
    try:
        return app.request_context.request_id
    except LookupError:
        return None


def _workspace_root() -> Any:
    try:
        return workspace_monitor.allowed_directories[0]
    except (AttributeError, IndexError, TypeError):
        return None


def _may_elicit(name: str, arguments: Any) -> bool:
    """Ask only where an answer can be used: never for approval tools, never for a call that
    carries a plan_id, and never for a call the gate would refuse without an approved plan
    (an answer changes the arguments, so it cannot match an approved action)."""
    if not elicitation_allowed(name):
        return False
    if isinstance(arguments, dict) and arguments.get("plan_id"):
        return False
    gate = getattr(approval_provider, "gate", None)
    try:
        tool_def = registry.lookup_tool(name)
        if gate is None or tool_def is None or not tool_def.is_mutating:
            return True
        return not requires_approval(registry, name, tool_def, arguments) or gate.approval_mode == "auto"
    except Exception:
        return False  # fail closed: no question, plain refusal


async def _call_tool_once(name: str, arguments: Any) -> list[TextContent] | CallToolResult | CreateTaskResult:
    if name in HUMAN_ONLY_TOOLS:
        return _tool_error("human_only", (
            f"Error: '{name}' is not available to AI clients. A person approves, rejects and rolls back "
            "plans in the Revit panel or with the aec-model-bridge-approve command. Ask them to do it."
        ))

    try:
        provider = registry.lookup_tool_provider(name)
    except ToolProfileBlocked as exc:
        return _tool_error("tool_profile_blocked", str(exc))
    if not provider:
        return _tool_error("unknown_tool", f"Error: Unknown tool '{name}'")
    _count_call(name)

    try:
        read_only = is_read_only_tool(name, registry.lookup_tool(name))
    except Exception:
        read_only = False  # fail closed: full indented output, no trimming

    try:
        arguments, response_options = split_response_options(name, arguments, read_only)
    except ValueError as exc:
        return _tool_error("invalid_response_options", str(exc))

    # A task-augmented call (the client sent a `task` field) is refused before any
    # approved action is claimed when the tool cannot run as a task.
    task_metadata = mcp_tasks.request_task_metadata(app) if TASKS_ENABLED else None
    if task_metadata is not None and name not in mcp_tasks.TASK_TOOLS:
        return _tool_error("task_not_supported", (
            f"'{name}' cannot run as a task. Call it without the task field. Only tools listed with "
            "execution.taskSupport 'optional' accept task-augmented calls."
        ))

    # A missing export file name is found before the approval gate, so no approved action is used up.
    need = missing_export_path(name, arguments, _workspace_root())
    if need is not None:
        raise need

    # Approval gate: a mutating call consumes its approved action here, before it
    # runs, so it can run at most once even if it fails or is called concurrently.
    gate = approval_provider.gate
    try:
        claim = gate_before(registry, gate, name, arguments)
    except ToolProfileBlocked as e:
        return _tool_error("tool_profile_blocked", str(e))
    except Exception as e:
        return _tool_error("approval_blocked", f"Approval Gate Blocked: {str(e)}")

    cursor_ctx = _cursor_context(name, arguments, response_options) if read_only else None
    if "cursor" in response_options:
        # The next part of a trimmed read comes from memory; the tool does not run again.
        if cursor_ctx is None or claim is not None:
            return _tool_error("invalid_cursor", f"'{name}' does not take a cursor.")
        try:
            page = next_page(response_options, cursor_ctx)
        except CursorError as exc:
            return _tool_error("invalid_cursor", str(exc))
        return _text_only(name, f"✓ {name} next part (from cursor, not run again)\n\nResult:\n{page}")

    if task_metadata is not None:
        return await _start_task(name, provider, arguments, claim, gate, response_options, read_only, task_metadata)

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
            # The action was consumed above, when the job is queued; the job records
            # how it ended. A job that fails needs a new plan.
            async def run_tool_job(context=None):
                try:
                    with authorized_module_execution(name):
                        result = await provider.execute_tool(name, arguments)
                except BaseException as e:
                    gate_after(gate, claim, ok=False, error=str(e) or type(e).__name__)
                    raise
                # A 'running' answer keeps the claim consumed and the action in flight until
                # revit_get_result returns the final result; it is not booked as done here.
                outcome = gate_after_result(gate, claim, name, result)
                if outcome.state == "failed":
                    raise BridgeError(f"Tool returned failure: {json.dumps(redact_data(result))}")
                return result

            job_ref = await job_manager.submit(
                run_tool_job,
                idempotency_key=idempotency_key
            )
            response_text = f"✓ Job {job_ref.job_id} queued successfully\n\n"
            response_text += f"Result:\n{json.dumps(job_ref.to_dict(), indent=2)}"
            return _text_only(name, response_text)
    except CommandFailed as e:
        return _tool_error("bridge_error", f"Revit Bridge Error: {str(e)}", result=e.payload)
    except ToolProfileBlocked as e:
        return _tool_error("tool_profile_blocked", str(e))
    except BridgeError as e:
        return _tool_error("bridge_error", f"Revit Bridge Error: {str(e)}")
    except Exception as e:
        return _tool_error("execution_error", f"Error: {str(e)}")

    return await _execute_and_present(name, provider, arguments, claim, gate, response_options, read_only)


async def _execute_and_present(name, provider, arguments, claim, gate, response_options, read_only,
                               follow_job: bool = False) -> list[TextContent] | CallToolResult:
    """Run the tool, book the approval outcome and format the reply (direct calls and tasks)."""
    cursor_ctx = _cursor_context(name, arguments, response_options) if read_only else None
    try:
        # Execute the tool on the provider
        try:
            with authorized_module_execution(name):
                result = await provider.execute_tool(name, arguments)
        except BaseException as e:
            gate_after(gate, claim, ok=False, error=str(e) or type(e).__name__)
            settle_in_flight(gate, name, arguments, error=e)
            raise
        if follow_job and name == mcp_tasks.RUN_JOB_TOOL:
            # A revit_run_job task waits for the Revit job's real outcome. If the task is
            # cancelled meanwhile, the action is booked as still running, never as failed.
            result = await mcp_tasks.follow_revit_job(
                provider, result, lambda last: gate_after_result(gate, claim, name, last),
            )
        if claim is None:
            settle_in_flight(gate, name, arguments, result=result)
        outcome = gate_after_result(gate, claim, name, result)
        failed = outcome.state == "failed" or _result_failed(result)

        redacted_result = redact_data(result)

        if outcome.state == "running":
            # Not an error and not done: Revit is still working and the approved action stays
            # consumed (it cannot be replayed) until revit_get_result brings the final result.
            kept = ("; the approved action stays used and cannot be run again" if claim else "")
            text = (
                f"{name} is still running. It has not finished and it has not failed{kept}. "
                f"Resume with {outcome.resume}. Do not repeat the call.\n\n"
                f"Result:\n{result_json(redacted_result, response_options, project=False)}"
            )
            return _text_only(name, text)

        # Format the response
        body = result_json(
            redacted_result, response_options, project=not failed, read_only=read_only, cursor=cursor_ctx)
        response_text = f"{name} returned a failure\n\n" if failed else f"✓ {name} executed successfully\n\n"
        response_text += f"Result:\n{body}"

        if failed:
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text=response_text)],
                structuredContent=redacted_result,
            )
        content: list = [TextContent(type="text", text=response_text)]
        if cursor_ctx is not None and cursor_ctx.resource_uri:
            content.append(ResourceLink(
                type="resource_link", uri=cursor_ctx.resource_uri, name=f"{name} full result",
                mimeType=mcp_resources.MIME,
            ))
        if output_schema_for(name) is not None:
            # Structured output is the same JSON the text shows, checked against the tool's schema.
            return CallToolResult(content=content, structuredContent=structured_for(name, _json_object(body)))
        return content

    except InputNeeded:
        raise  # call_tool asks the person or returns the plain refusal
    except CommandFailed as e:
        return _tool_error("bridge_error", f"Revit Bridge Error: {str(e)}", result=e.payload)
    except ToolProfileBlocked as e:
        return _tool_error("tool_profile_blocked", str(e))
    except BridgeError as e:
        return _tool_error("bridge_error", f"Revit Bridge Error: {str(e)}")

    except Exception as e:
        return _tool_error("execution_error", f"Error: {str(e)}")


def _call_writes(name: str, arguments: Any) -> bool:
    """True unless this call provably cannot change the model (fails closed)."""
    try:
        return requires_approval(registry, name, registry.lookup_tool(name), arguments)
    except Exception:
        return True


async def _start_task(name, provider, arguments, claim, gate, response_options, read_only, task_metadata):
    """Queue an already-gated call as an MCP task and return its CreateTaskResult."""
    async def work() -> CallToolResult:
        reply = await _execute_and_present(
            name, provider, arguments, claim, gate, response_options, read_only, follow_job=True,
        )
        return reply if isinstance(reply, CallToolResult) else CallToolResult(content=list(reply), isError=False)

    def cancelled_before_start() -> None:
        gate_after(gate, claim, ok=False, error="Task cancelled before it started; nothing ran.")

    try:
        return await task_bridge.start(
            tool=name,
            writes=_call_writes(name, arguments),
            metadata=task_metadata,
            scope=mcp_tasks.session_scope(app),
            work=work,
            on_cancel_before_start=cancelled_before_start,
        )
    except Exception as e:
        # Nothing was queued, so nothing ran; the claimed action is booked as failed.
        gate_after(gate, claim, ok=False, error=str(e) or type(e).__name__)
        return _tool_error("execution_error", f"Error: the task could not be started: {str(e)}")


_result_failed = result_failed


def _cursor_context(name: str, arguments: Any, options: dict) -> CursorContext:
    """Binds a cursor to this tool, its arguments and fields; names the workspace for saved results."""
    workspace = None
    if workspace_monitor is not None and getattr(workspace_monitor, "allowed_directories", None):
        workspace = workspace_monitor.allowed_directories[0]
    return CursorContext(name, cursor_binding(name, arguments, options.get("fields")), workspace)


def _text_only(name: str, text: str) -> list[TextContent] | CallToolResult:
    """A text answer with no structured output (queued job, still running).

    For a tool with an outputSchema it is returned as a CallToolResult, which the SDK passes
    through as is; a bare content list would fail the SDK's output check."""
    content = [TextContent(type="text", text=text)]
    if output_schema_for(name) is not None:
        return CallToolResult(content=content)
    return content


def _json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _count_call(name: str) -> None:
    """Count one call of a listed tool by name only (usage_counts.py). Never fails the call."""
    counter = getattr(registry, "usage_counter", None)
    if counter is None:
        return
    try:
        counter.record(name)
    except Exception as exc:
        logger.debug("Tool usage count skipped: %s", exc)


def redact_data(value):
    """Secrets and paths always; personal data when MCP_REVIT_REDACT_RESPONSES is set."""
    return redact_response(_redact_secrets(value))


def _tool_error(kind: str, message: str, result: dict | None = None) -> CallToolResult:
    """Preserve readable diagnostics while telling MCP clients the call failed."""
    message = redact_data(message)
    structured = {"ok": False, "error": {"kind": kind, "message": message}}
    if result is not None:
        structured["result"] = redact_data(result)
        message += "\n\nResult:\n" + json.dumps(structured["result"], indent=2)
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=message)],
        structuredContent=structured,
    )

async def main():
    """Run the MCP server."""
    global registry, approval_provider, job_manager, workspace_monitor
    profile = load_tool_profile()  # fail invalid settings before provider construction
    if profile.detail:
        logger.info(profile.detail)
    from .config import config
    from .usage_counts import start_counter
    counter = start_counter(config.workspace_dir)  # local file only; MCP_REVIT_USAGE_COUNTS=off disables
    registry, approval_provider, job_manager, _module_registry, workspace_monitor = build_registry()
    try:
        registry.usage_counter = counter
        registry.freeze_tool_profile(profile)
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    finally:
        counter.flush()
        await job_manager.shutdown(cancel_running=True)

def run_mcp_server():
    """Entry point for running the MCP server."""
    import sys

    if sys.argv[1:2] == ["doctor"]:
        from .doctor import main as doctor_main

        sys.exit(doctor_main(sys.argv[2:]))

    from .cli_flags import handle_standard_flags

    handle_standard_flags(
        "aec-model-bridge",
        "AEC Model Bridge MCP server (stdio). MCP clients start it with no arguments; "
        "settings come from MCP_REVIT_* environment variables (see docs/configuration-reference.md).",
    )
    asyncio.run(main())


if __name__ == "__main__":
    run_mcp_server()
