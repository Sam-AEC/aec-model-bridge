#!/usr/bin/env python
"""Measure an MCP tool catalogue and representative mock responses.

Run with the server's Python environment, e.g.:
  python scripts/measure_mcp_tokens.py --output docs/mcp-token-measurement-after.json
  python scripts/measure_mcp_tokens.py --profile daily --compact-read-results \
      --project-module-commands --output docs/mcp-token-measurement-daily.json

Counts are characters, UTF-8 bytes, and an explicit chars/4 estimate, not billed
tokens. Uses actual list_tools/call_tool entry points, no Revit or model writes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def dump(value):
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json(by_alias=True, exclude_none=True)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def size(text):
    return {"chars": len(text), "utf8_bytes": len(text.encode("utf-8")),
            "approx_tokens_chars_div_4": round(len(text) / 4, 2)}


async def measure(workspace, *, profile="full", profile_file=None,
                  compact_read_results=False, project_module_commands=False,
                  plan_script_chars=0, omit_plan_arguments=False):
    # Deliberately stable default catalogue; no credentials/proxies/user modules.
    for key in list(os.environ):
        if key.startswith(("APS_", "SPECKLE_", "MCP_PROXY_", "MCP_REVIT_")):
            del os.environ[key]
    os.environ.update(MCP_REVIT_MODE="mock", MCP_REVIT_WORKSPACE_DIR=str(workspace),
                      MCP_REVIT_ALLOWED_DIRECTORIES=str(workspace),
                      MCP_REVIT_ENABLE_USER_MODULES="false", MCP_REVIT_APPROVAL_MODE="ask_first",
                      MCP_REVIT_AUDIT_LOG=str(workspace / "audit.log"))
    sys.path.insert(0, str(ROOT / "packages/mcp-server-revit/src"))
    from mcp.types import CallToolResult, ListToolsResult, Tool
    from revit_mcp_server import mcp_server
    from revit_mcp_server.providers.module_provider import tool_name_of
    from revit_mcp_server.registry_factory import build_registry
    from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS
    from revit_mcp_server.security.workspace import WorkspaceMonitor
    from revit_mcp_server.tool_profiles import load_tool_profile

    registry, approval, jobs, modules, _ = build_registry(WorkspaceMonitor([workspace]))
    profile_settings = {"MCP_REVIT_TOOL_PROFILE": profile}
    if profile_file is not None:
        profile_settings["MCP_REVIT_TOOL_PROFILE_FILE"] = str(profile_file)
    registry.freeze_tool_profile(load_tool_profile(profile_settings))
    mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = registry, approval, jobs
    listed = await mcp_server.list_tools()
    listed_names = {tool.name for tool in listed}
    full = ListToolsResult(tools=listed)
    ownership, explicit_module_ownership, raw = {}, {}, []
    for provider in registry.get_all_providers():
        for tool in provider.get_capabilities():
            if tool.name in HUMAN_ONLY_TOOLS or tool.name not in listed_names:
                continue
            ownership[tool.name] = provider.get_identity()
            if getattr(tool, "module_id", None):
                explicit_module_ownership[tool.name] = tool.module_id
            raw.append(Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema))
    module_ownership = {tool_name_of(module.manifest.id, command): module.manifest.id
                        for module in modules.get_all_modules() for command in module.manifest.commands}
    module_ownership.update(explicit_module_ownership)
    by_provider, by_module = defaultdict(list), defaultdict(list)
    tool_rows = []
    for tool in listed:
        encoded = dump(tool)
        by_provider[ownership[tool.name]].append(tool)
        if tool.name in module_ownership:
            by_module[module_ownership[tool.name]].append(tool)
        tool_rows.append({"name": tool.name, "provider": ownership[tool.name],
                          "module": module_ownership.get(tool.name), "tool": size(encoded),
                          "input_schema": size(dump(tool.inputSchema))})

    def group_sizes(groups):
        return {key: {"tools": len(value), **size(dump(ListToolsResult(tools=value)))}
                for key, value in sorted(groups.items())}

    full_text, raw_text = dump(full), dump(ListToolsResult(tools=raw))
    result = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": (await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        )).strip(),
        "method": {"entrypoints": ["mcp_server.list_tools", "mcp_server.call_tool"],
                   "profile": profile, "profile_file": str(profile_file) if profile_file else None,
                   "compact_read_results": compact_read_results,
                   "project_module_commands": project_module_commands,
                   "plan_script_chars": plan_script_chars,
                   "omit_plan_arguments": omit_plan_arguments,
                   "serialization": "MCP SDK model_dump_json(by_alias=True, exclude_none=True), compact UTF-8 JSON",
                   "catalogue_payload": "ListToolsResult; excludes JSON-RPC envelope/transport framing",
                   "raw_baseline": "same providers, Tool(name, description, inputSchema) without enrich_tool",
                   "environment": "mock; credentials/proxy env scrubbed; user modules disabled; temporary isolated workspace",
                   "token_estimate": "characters / 4; not actual model tokenizer or client context billing",
                   "live_results_limit": "Mock returns tiny canned payloads; these cannot establish live Revit result sizes."},
        "tool_count": len(listed), "human_only_not_listed": sorted(HUMAN_ONLY_TOOLS),
        "catalogue": size(full_text), "raw_catalogue": size(raw_text),
        "metadata_delta": {key: size(full_text)[key] - size(raw_text)[key] for key in size(full_text)},
        "names_only_json": size(dump([tool.name for tool in listed])),
        "by_provider": group_sizes(by_provider), "by_module": group_sizes(by_module),
        "top_15_tools": sorted(tool_rows, key=lambda row: row["tool"]["chars"], reverse=True)[:15],
        "tools": tool_rows,
    }
    calls = [
        ("module_list_commands", {}), ("revit_list_elements", {"category": "Walls"}),
        ("revit_list_families", {}), ("revit_get_element_parameters", {"element_id": 123}),
        ("revit_list_views", {}),
        ("plan_actions", {"actions": [{"tool": "revit_set_parameter_value", "arguments": {
            "element_id": 123, "parameter_name": "Comments", "value": "Measurement only"}}]}),
    ]
    if plan_script_chars:
        # Pending plan only: this script is never approved or executed.
        calls[-1] = ("plan_actions", {"actions": [{"tool": "revit_execute_python", "arguments": {
            "script": "#" + "x" * (plan_script_chars - 1), "mode": "write"}}]})
    if compact_read_results:
        calls = [(name, {**arguments, "response_options": {"compact": True}})
                 for name, arguments in calls]
    if project_module_commands:
        calls.append(("module_list_commands", {"response_options": {
            "compact": True, "fields": ["modules.id", "modules.commands.id"]}}))
    if omit_plan_arguments:
        calls = [(name, {**arguments, "response_options": {
            **arguments.get("response_options", {}), "omit_action_arguments": True}})
                 if name == "plan_actions" else (name, arguments) for name, arguments in calls]
    result["calls"] = []
    for name, arguments in calls:
        response = await mcp_server.call_tool(name, arguments)
        wire = response if isinstance(response, CallToolResult) else CallToolResult(content=response)
        texts = [content.text for content in wire.content if content.type == "text"]
        parsed = wire.structuredContent
        if texts and "Result:\n" in texts[0]:
            parsed = json.loads(texts[0].split("Result:\n", 1)[1])
        elif parsed is None and texts:
            try:
                parsed = json.loads(texts[0])
            except ValueError:
                pass
        result["calls"].append({"name": name, "arguments": arguments,
                                "request_arguments": size(dump(arguments)),
                                "script_chars": sum(len(str(action.get("arguments", {}).get("script", ""))) for action in arguments.get("actions", [])),
                                "response": size(dump(wire)), "text_content": size("".join(texts)),
                                "parsed_result_compact": size(dump(parsed)) if parsed is not None else None,
                                "is_error": bool(wire.isError), "observed": wire.model_dump(by_alias=True, exclude_none=True)})
    await jobs.shutdown(cancel_running=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("full", "daily", "custom"), default="full")
    parser.add_argument("--profile-file", type=Path)
    parser.add_argument("--compact-read-results", action="store_true",
                        help="Request compact text on the same five reads and pending plan fixture")
    parser.add_argument("--project-module-commands", action="store_true",
                        help="Add a compact module listing projected to module and command IDs")
    parser.add_argument("--plan-script-chars", type=int, default=0,
                        help="Replace the parameter plan with an unexecuted script of this many characters")
    parser.add_argument("--omit-plan-arguments", action="store_true",
                        help="Request omission of echoed action arguments in the pending-plan response")
    args = parser.parse_args()
    if args.profile == "custom" and args.profile_file is None:
        parser.error("--profile custom requires --profile-file")
    if args.plan_script_chars < 0:
        parser.error("--plan-script-chars must be nonnegative")
    with tempfile.TemporaryDirectory(prefix="aec-token-measure-") as directory:
        result = asyncio.run(measure(Path(directory), profile=args.profile,
                                    profile_file=args.profile_file,
                                    compact_read_results=args.compact_read_results,
                                    project_module_commands=args.project_module_commands,
                                    plan_script_chars=args.plan_script_chars,
                                    omit_plan_arguments=args.omit_plan_arguments))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("tool_count", "catalogue", "raw_catalogue", "metadata_delta", "names_only_json")}, indent=2))
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
