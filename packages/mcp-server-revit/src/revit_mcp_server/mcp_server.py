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

from . import call_limits, client_roots, mcp_apps, mcp_logging, mcp_prompts, mcp_resources, mcp_tasks

from .elicitation import (
    MAX_ROUNDS, VIEW_SHEET_REFS, ElicitationForbidden, InputNeeded, check_view_sheet_names, elicit_choice,
    client_supports_url_elicitation, elicitation_allowed, missing_export_path, offer_plan_panel_link,
)
from .errors import BridgeError, CommandFailed
from .registry_factory import build_registry
from .security.approval import HUMAN_ONLY_TOOLS
from .security.policy import name_in_off_tier, off_tiers_for_listing, tool_refusal
from .security.workspace import CLIENT_ROOTS
from .security.dispatch import (
    GET_RESULT_TOOL, gate_after, gate_after_result, gate_before, mark_timed_out, result_failed,
    settle_in_flight, settle_late_result,
)
from .security.gating import requires_approval
from .security.audit import redact_data as _redact_secrets
from .security.response_redaction import redact_response
from .security.module_execution import authorized_module_execution
from .output_schemas import fallback_structured, output_schema_for, structured_for
from .tool_metadata import is_read_only_tool
from .read_cursor import Context as CursorContext, CursorError, binding as cursor_binding
from .result_presentation import APPROVAL_TOOLS, next_page, result_json, split_response_options
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
client_roots.register(app)

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

# Per-tool timeouts and rate limits (call_limits.py). Read from the environment on first use;
# tests replace them with fakes.
call_limiter: call_limits.RateLimiter | None = None
tool_timeouts: call_limits.Timeouts | None = None


def _limiter() -> call_limits.RateLimiter:
    global call_limiter
    if call_limiter is None:
        call_limiter = call_limits.RateLimiter()
    return call_limiter


def _timeouts() -> call_limits.Timeouts:
    global tool_timeouts
    if tool_timeouts is None:
        tool_timeouts = call_limits.Timeouts.from_env()
    return tool_timeouts


def _session_key() -> str:
    session = _client_session()
    return "direct" if session is None else f"session-{id(session)}"


def _identity(provider: Any) -> str:
    getter = getattr(provider, "get_identity", None)
    return str(getter()) if callable(getter) else ""


mcp_logging.install()


@app.set_logging_level()
async def set_logging_level(level: str) -> None:
    """logging/setLevel: server log messages at or above this level reach this client as notifications."""
    session = _client_session()
    if session is not None:
        mcp_logging.handler.set_level(session, level)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available AEC tools from registered providers."""
    # listed_tool runs enrich_tool, which adds parameter docs and behaviour annotations (readOnlyHint,
    # destructiveHint, idempotentHint, openWorldHint) without changing behaviour.
    # For MCP Tasks it also sets execution.taskSupport on mcp_tasks.TASK_TOOLS.
    # For a client that declared the MCP Apps extension (or MCP_REVIT_MCP_APPS=always), plan tools
    # name the read-only plan review view and every tool that is not read-only is marked callable
    # by the model only, never by an app (mcp_apps.py). Worked out per request, never cached.
    # Tools of a tier that policy turns off are hidden (policy.off_tiers_for_listing). Dev mode lifts
    # that at list time. This server sends no tools/list_changed, so a client re-lists after Dev mode
    # or a policy file changes.
    gate = getattr(approval_provider, "gate", None)
    off = off_tiers_for_listing(getattr(gate, "workspace_dir", None), bool(getattr(gate, "dev_mode", False)))
    return [
        mcp_apps.listed_tool(provider.get_identity(), t)
        for provider, t in registry.get_tools_with_providers()
        if t.name not in HUMAN_ONLY_TOOLS
        and not (off and name_in_off_tier(t.name, t, provider.get_identity(), off))
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
    if str(uri).startswith("ui://"):
        html, meta = mcp_apps.read_resource(uri, approval_provider.gate)
        return [ReadResourceContents(content=html, mime_type=mcp_apps.MIME, meta=meta)]
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

    The folders this client has open (MCP roots) narrow the workspace sandbox for the call
    (client_roots.py); they never widen it.
    """
    roots = await client_roots.for_session(_client_session(), workspace_monitor)
    token = CLIENT_ROOTS.set(roots)
    try:
        return await _call_tool_rounds(name, arguments)
    finally:
        CLIENT_ROOTS.reset(token)


async def _call_tool_rounds(name: str, arguments: Any) -> list[TextContent] | CallToolResult | CreateTaskResult:
    rounds = 0
    while True:
        try:
            result = await _call_tool_once(name, arguments)
            if name == "plan_actions":
                _offer_panel_link(result)
            return result
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


def _pending_plan_id(result: Any) -> str | None:
    """The id of the plan a plan_actions reply drafted, or None when it drafted none."""
    if isinstance(result, CallToolResult):
        if result.isError:
            return None
        data = result.structuredContent
        if not isinstance(data, dict):
            data = None
        content = result.content
    else:
        data, content = None, result
    if data is None:
        text = next((c.text for c in content or [] if isinstance(c, TextContent)), "")
        data = _json_object(text.split("Result:\n", 1)[1]) if "Result:\n" in text else None
    if isinstance(data, dict) and data.get("state") == "pending" and isinstance(data.get("plan_id"), str):
        return data["plan_id"]
    return None


_link_tasks: "set[asyncio.Task]" = set()  # strong references, so a running task is not collected


def _offer_panel_link(result: Any) -> None:
    """Send the review panel link for a newly drafted plan to a client that supports URL mode.
    It runs in the background so the plan_actions reply is not held up by a slow client.
    The link only points at the panel; it never approves. Any failure leaves the reply as is."""
    try:
        plan_id = _pending_plan_id(result)
        session = _client_session()
        if plan_id and client_supports_url_elicitation(session):
            task = asyncio.get_running_loop().create_task(_send_panel_link(session, plan_id, _request_id()))
            _link_tasks.add(task)
            task.add_done_callback(_link_tasks.discard)
    except Exception as exc:  # the plan is drafted; the link is a convenience
        logger.info("Panel link skipped: %s", type(exc).__name__)


async def _send_panel_link(session: Any, plan_id: str, request_id: Any) -> None:
    try:
        await offer_plan_panel_link(session, plan_id, related_request_id=request_id)
    except Exception as exc:
        logger.info("Panel link skipped: %s", type(exc).__name__)


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


VIEW_SHEET_LIST_TOOL = "revit_list_views_sheets_schedules"
VIEW_SHEET_LIST_LIMIT = 500


async def _list_views_or_sheets(kind: str, needle: str) -> tuple[list[dict], int] | None:
    """Views (with schedules, which Revit also resolves by name) or sheets whose name or number
    contains ``needle``, through the read-only list tool. None when it cannot run (mock mode,
    hidden by the profile, no Revit, an error); then nothing is asked."""
    args = {
        "kinds": ["views", "schedules"] if kind == "view" else ["sheets"],
        "name_contains": needle, "limit": VIEW_SHEET_LIST_LIMIT, "fields": ["kind", "id", "name", "number", "type"],
    }
    try:
        provider = registry.lookup_tool_provider(VIEW_SHEET_LIST_TOOL)
        tool_def = registry.lookup_tool(VIEW_SHEET_LIST_TOOL)
        if provider is None or tool_def is None or tool_def.is_mutating:
            return None
        if gate_before(registry, approval_provider.gate, VIEW_SHEET_LIST_TOOL, args) is not None:
            return None
        with authorized_module_execution(VIEW_SHEET_LIST_TOOL):
            result = await provider.execute_tool(VIEW_SHEET_LIST_TOOL, args)
    except Exception as exc:  # no question; the tool resolves the name itself
        logger.info("Could not list %ss for a name check: %s", kind, exc)
        return None
    if not isinstance(result, dict) or result.get("mock") or result.get("ok") is not True:
        return None
    rows = [r for r in result.get("rows") or [] if isinstance(r, dict) and r.get("id") is not None]
    if kind == "sheet":
        rows = [r for r in rows if r.get("number")]
    total = (result.get("limits") or {}).get("rows_total")
    return rows, total if isinstance(total, int) and total >= len(rows) else len(rows)


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

    # Tier policy (machine and workspace files). Control tools are never refused.
    policy_gate = getattr(approval_provider, "gate", None)
    try:
        tier_msg = tool_refusal(getattr(policy_gate, "workspace_dir", None), name, registry.lookup_tool(name),
                                _identity(provider), bool(getattr(policy_gate, "dev_mode", False)))
    except Exception as exc:  # fail closed: a tool whose tier cannot be worked out is not run
        tier_msg = f"Policy refused '{name}': its tier could not be worked out ({str(exc)[:120]})."
    if tier_msg is not None:
        return _tool_error("policy_refused", tier_msg)

    # Rate limits run before the approval gate, so a refused call never uses an approved action.
    # Approval tools never get here: they are human-only and refused above.
    refusal = _limiter().check_tool(_session_key(), name, _call_writes(name, arguments))
    if refusal is not None:
        return _tool_error("rate_limited", refusal.message(),
                           details={"retry_after_seconds": refusal.retry_after_seconds})
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
    # A view name or sheet number that Revit would not match to exactly one view or sheet is asked
    # about, or refused with the candidates, before the gate. Only where an answer can be used:
    # a call that needs an approved plan keeps its arguments and Revit resolves the name itself.
    if name in VIEW_SHEET_REFS and _may_elicit(name, arguments):
        need = await check_view_sheet_names(name, arguments, _list_views_or_sheets)
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
        return _text_only(name, f"✓ {name} next part (from cursor, not run again)\n\nResult:\n{page}",
                          _json_object(page), "This reply is a cursor page of an earlier result, not the full result.")

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
            return _text_only(name, response_text, None, "The call was queued as a job; it has no result yet.")
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
                               follow_job: bool = False, on_job=None) -> list[TextContent] | CallToolResult:
    """Run the tool, book the approval outcome and format the reply (direct calls and tasks)."""
    cursor_ctx = _cursor_context(name, arguments, response_options) if read_only else None
    # Direct calls have a timeout; a task follows the real outcome and has none.
    # execute_plan runs approved actions itself and books each one; it has no outer timeout.
    timeout = None if follow_job or name in call_limits.NO_TIMEOUT_TOOLS else _timeouts().for_tool(name)
    # Only a provably read-only call may be cancelled on timeout. Anything else (a claimed action,
    # a mutating tool, an orchestration tool whose capability says is_mutating=False but runs gated
    # actions inside, or a call whose classification fails) keeps running: fail closed.
    writes = timeout is not None and not _provably_read_only(name, arguments, claim, read_only)

    async def run() -> Any:
        # The authorization scope lives as long as the provider call, also when a timed-out
        # write keeps running in the background.
        with authorized_module_execution(name):
            return await provider.execute_tool(name, arguments)

    try:
        # Execute the tool on the provider
        try:
            result = await call_limits.run_with_timeout(run(), timeout, keep_running=writes)
        except call_limits.ToolTimedOut as timed_out:
            return _timed_out(name, arguments, claim, gate, timed_out)
        except BaseException as e:
            gate_after(gate, claim, ok=False, error=str(e) or type(e).__name__)
            settle_in_flight(gate, name, arguments, error=e)
            raise
        if follow_job:
            # A task waits for the real outcome: a revit_run_job for its Revit job, and any task
            # tool for a request the bridge answered as still running (revit_get_result). If the
            # task is cancelled meanwhile, the action is booked as still running, never as failed.
            def book_running(last: Any) -> None:
                gate_after_result(gate, claim, name, last)

            try:
                if name == mcp_tasks.RUN_JOB_TOOL:
                    result = await mcp_tasks.follow_revit_job(provider, result, book_running, on_job)
                result = await mcp_tasks.follow_revit_result(_fetch_revit_result, name, result, book_running)
            except CommandFailed as e:
                gate_after(gate, claim, ok=False, error=str(e) or type(e).__name__)
                raise
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
            return _text_only(name, text, None, "The call is still running; it has no final result yet.")

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
        # Plan tools: the approval mode goes in _meta for the MCP Apps view; the plan JSON is unchanged.
        view_meta = mcp_apps.result_meta(name, gate)
        if output_schema_for(name) is not None:
            # Structured output is the same JSON the text shows, checked against the tool's schema.
            return CallToolResult(
                content=content, structuredContent=structured_for(name, _json_object(body)), **view_meta)
        if view_meta:
            return CallToolResult(content=content, **view_meta)
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


def _timed_out(name, arguments, claim, gate, timed_out: call_limits.ToolTimedOut):
    """Reply for a call that outlived its timeout.

    A read was cancelled and is refused with kind tool_timeout. A write was not cancelled and is
    not reported as failed: it may still be running in Revit. Its approved action stays used and is
    recorded as in flight, like a 'running' result, so it is never replayed; if the call finishes
    while this server runs, the action is closed with the real result."""
    seconds = f"{timed_out.seconds:g}"
    if not timed_out.kept_running:
        return _tool_error("tool_timeout", (
            f"{name} did not finish within {seconds} s and was stopped. It is a read, so nothing in the model "
            f"changed. Try a smaller request, or ask the person to raise the timeout "
            f"({call_limits.TIMEOUTS_ENV}, for example {{\"{name}\": 900}})."
        ), details={"timeout_seconds": timed_out.seconds})

    key = mark_timed_out(gate, claim, name)

    def finished(task) -> None:
        if task.cancelled():
            return  # outcome unknown: the action stays running for a person to recover
        error = task.exception()
        result = None if error else task.result()
        if key is not None:
            settle_late_result(gate, key, name, result=result, error=error)
        else:
            # No claim of its own (revit_get_result, revit_job_status, an orchestrator): book
            # the outcome it carries for an in-flight action, as a call that finished in time does.
            settle_in_flight(gate, name, arguments, result=result, error=error)

    timed_out.task.add_done_callback(finished)
    if key is not None:
        kept = (
            f" The approved action stays used and cannot be run again. It is recorded as running under {key}; "
            "if the call finishes while this server runs, the action is closed with its real result. If it never "
            f"does, a person can run `aec-model-bridge-approve recover {claim.get('plan_id')} --reason ...`."
        )
    else:
        kept = ""
    text = (
        f"{name} did not finish within {seconds} s. It may still be running in Revit: it has not finished "
        f"and it has not been reported as failed.{kept} Do not repeat the call. Check the model with a read "
        "tool before doing anything else."
    )
    return _text_only(name, text, None, "The call timed out and may still be running; it has no result yet.")


async def _fetch_revit_result(request_id: str) -> Any:
    """revit_get_result for a task that follows a running request (read-only, never re-runs)."""
    provider = registry.lookup_tool_provider(GET_RESULT_TOOL)
    if provider is None:
        raise BridgeError(f"{GET_RESULT_TOOL} is not available to follow request {request_id}.")
    return await provider.execute_tool(GET_RESULT_TOOL, {"request_id": request_id})


def _provably_read_only(name: str, arguments: Any, claim: Any, read_only: bool) -> bool:
    """True only when a timed-out call may be cancelled: it cannot change the model.

    False for a claimed action, an approval or plan tool (execute_plan, plan_revert, revit_run_job,
    revit_get_result: they run or book gated actions although some say is_mutating=False), any
    other ApprovalProvider tool, a mutating tool (also revit_execute_python in read mode), and
    when the check itself fails. Fails closed."""
    if claim is not None or not read_only or name in APPROVAL_TOOLS:
        return False
    try:
        provider = registry.lookup_tool_provider(name)
        if approval_provider is not None and provider is approval_provider:
            return False
        if not is_read_only_tool(name, registry.lookup_tool(name)):
            return False
        return not _call_writes(name, arguments)
    except Exception:
        return False


def _call_writes(name: str, arguments: Any) -> bool:
    """True unless this call provably cannot change the model (fails closed)."""
    try:
        return requires_approval(registry, name, registry.lookup_tool(name), arguments)
    except Exception:
        return True


async def _start_task(name, provider, arguments, claim, gate, response_options, read_only, task_metadata):
    """Queue an already-gated call as an MCP task and return its CreateTaskResult."""
    writes = _call_writes(name, arguments)
    canceller = None
    run_arguments = arguments
    reuses_job = isinstance(arguments, dict) and bool(arguments.get("idempotency_key"))
    # An idempotency_key can hand back an existing job (JobManager dedups by key alone), which may be a
    # queued write: then the task never cancels the inner job (#335 review).
    if name == mcp_tasks.RUN_JOB_TOOL and not writes and claim is None and not reuses_job:
        # Read-only revit_run_job: tasks/cancel may cancel the inner Revit job, so its id is needed at
        # once. wait_s=0 returns the job id straight away; the task follows the job either way.
        canceller = mcp_tasks.RevitJobCanceller(provider)
        run_arguments = {**arguments, "wait_s": 0}

    async def work() -> CallToolResult:
        reply = await _execute_and_present(
            name, provider, run_arguments, claim, gate, response_options, read_only, follow_job=True,
            on_job=canceller.note if canceller else None,
        )
        return reply if isinstance(reply, CallToolResult) else CallToolResult(content=list(reply), isError=False)

    def cancelled_before_start() -> None:
        gate_after(gate, claim, ok=False, error="Task cancelled before it started; nothing ran.")

    try:
        return await task_bridge.start(
            tool=name,
            writes=writes,
            metadata=task_metadata,
            scope=mcp_tasks.session_scope(app),
            work=work,
            on_cancel_before_start=cancelled_before_start,
            cancel_inner=canceller.cancel if canceller else None,
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


def _text_only(name: str, text: str, value: Any = None, reason: str = "") -> list[TextContent] | CallToolResult:
    """A successful answer that is not the tool's result (queued job, still running, cursor page).

    For a tool with an outputSchema it is a CallToolResult whose structuredContent is a fallback
    object that validates (output_schemas.fallback_structured): SDK clients that validate reject a
    reply from such a tool without structuredContent."""
    content = [TextContent(type="text", text=text)]
    if output_schema_for(name) is not None:
        return CallToolResult(content=content, structuredContent=fallback_structured(name, value, reason))
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


def _tool_error(kind: str, message: str, result: dict | None = None,
                details: dict | None = None) -> CallToolResult:
    """Preserve readable diagnostics while telling MCP clients the call failed.

    ``details`` adds fixed, non-secret fields to the error object (for example retry_after_seconds)."""
    message = redact_data(message)
    structured = {"ok": False, "error": {"kind": kind, "message": message, **(details or {})}}
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
