"""search_tools and context_report: read-only tools over the tool registry, in every profile.

The startup profile (core, daily, full) hides tools from tools/list. search_tools
still searches all of them and says which profile shows each hidden one, so a
client can ask the person to switch instead of guessing. Ranking is plain
token matching with a fixed tie-break on tool name, so results are repeatable.

context_report measures what the listed tools cost: the same serialization and
chars/4 estimate as scripts/measure_mcp_tokens.py, over the same list that
mcp_server.list_tools returns.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base import AECProvider, ProviderTool
from ..tool_profiles import CORE_TOOLS, DAILY_EXCLUDE, TOOL_SEARCH_PROVIDER_ID, ToolProfile

DEFAULT_LIMIT = 5
MAX_LIMIT = 25
REPORT_TOP = 10

_BUILTIN_PROFILES = (
    ToolProfile(name="full"),
    ToolProfile(name="daily", exclude=DAILY_EXCLUDE),
    ToolProfile(name="core", tools=CORE_TOOLS),
)
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class ToolSearchProvider(AECProvider):
    def __init__(self, registry: Any) -> None:
        self.registry = registry
        self._capabilities = [
            ProviderTool(
                name="search_tools",
                description=(
                    "Search every tool this server has, including tools the current profile hides, "
                    "and return the best matches with their schemas. Read-only. For a hidden tool "
                    "the result names the profile that shows it."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Words to look for in tool names, descriptions and hints such as read-only or destructive.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_LIMIT,
                            "description": f"Most matches to return. Default {DEFAULT_LIMIT}, at most {MAX_LIMIT}.",
                        },
                        "include_schema": {
                            "type": "boolean",
                            "description": "Include each match's input schema. Default true.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            ProviderTool(
                name="context_report",
                description=(
                    "Report what this server's tool list costs in context: active profile, listed tool "
                    "count, approximate characters and tokens (chars/4), the 10 largest tool definitions "
                    "and tips to use less. Read-only; estimates, not billed tokens."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
        ]

    def get_identity(self) -> str:
        return TOOL_SEARCH_PROVIDER_ID

    def get_capabilities(self) -> List[ProviderTool]:
        return self._capabilities

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy", "provider": TOOL_SEARCH_PROVIDER_ID}

    async def shutdown(self) -> None:
        pass

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = name.replace(".", "_")
        if name == "context_report":
            if arguments:
                raise ValueError("context_report takes no arguments.")
            return self.context_report()
        if name != "search_tools":
            raise ValueError(f"Unknown tool: {name}")
        query = arguments.get("query")
        if not isinstance(query, str) or not _words(query):
            raise ValueError("query must be a non-empty string with at least one word.")
        limit = arguments.get("limit", DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {MAX_LIMIT}.")
        include_schema = arguments.get("include_schema", True)
        if not isinstance(include_schema, bool):
            raise ValueError("include_schema must be true or false.")
        return self.search(query, limit, include_schema)

    def search(self, query: str, limit: int = DEFAULT_LIMIT, include_schema: bool = True) -> Dict[str, Any]:
        from ..security.approval import HUMAN_ONLY_TOOLS
        from ..tool_metadata import enrich_tool

        tokens = list(dict.fromkeys(_words(query)))
        active = getattr(self.registry, "_tool_profile", None)
        scored: list[tuple[int, str, dict[str, Any]]] = []
        total = 0
        for provider in self.registry.get_all_providers():
            pid = provider.get_identity()
            for tool in provider.get_capabilities():
                if tool.name in HUMAN_ONLY_TOOLS:
                    continue
                total += 1
                enriched = enrich_tool(pid, tool)
                score = _score(tokens, enriched)
                if score <= 0:
                    continue
                visible = active is None or active.allows(pid, tool.module_id, tool.name)
                profiles = [p.name for p in _BUILTIN_PROFILES if p.allows(pid, tool.module_id, tool.name)]
                ann = enriched.annotations
                item: dict[str, Any] = {
                    "name": tool.name,
                    "description": enriched.description,
                    "provider": pid,
                    "read_only": bool(ann and ann.readOnlyHint),
                    "destructive": bool(ann and ann.destructiveHint),
                    "visible_in_current_profile": visible,
                    "profiles": profiles,
                }
                if not visible:
                    item["note"] = _hidden_note(tool.name, active.name, profiles)
                if include_schema:
                    item["input_schema"] = enriched.inputSchema
                scored.append((score, tool.name, item))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return {
            "query": query,
            "current_profile": active.name if active else "full",
            "searched": total,
            "matched": len(scored),
            "returned": min(limit, len(scored)),
            "tools": [row[2] for row in scored[:limit]],
        }


    def context_report(self) -> Dict[str, Any]:
        from ..mcp_apps import listed_tool
        from ..security.approval import HUMAN_ONLY_TOOLS
        from ..tool_profiles import ALWAYS_LOADED_TOOLS

        active = getattr(self.registry, "_tool_profile", None)
        profile = active.name if active else "full"
        rows: list[dict[str, Any]] = []
        total_chars = 0
        always_chars = 0
        for provider, tool in self.registry.get_tools_with_providers():
            if tool.name in HUMAN_ONLY_TOOLS:
                continue
            chars = len(_dump(listed_tool(provider.get_identity(), tool)))
            total_chars += chars
            if tool.name in ALWAYS_LOADED_TOOLS:
                always_chars += chars
            rows.append({"name": tool.name, "provider": provider.get_identity(),
                         "chars": chars, "approx_tokens": _tokens(chars)})
        rows.sort(key=lambda row: (-row["chars"], row["name"]))
        listed = len(rows)
        return {
            "profile": profile,
            "listed_tools": listed,
            "chars": total_chars,
            "approx_tokens": _tokens(total_chars),
            "always_loaded": {"tools": sum(1 for r in rows if r["name"] in ALWAYS_LOADED_TOOLS),
                              "chars": always_chars, "approx_tokens": _tokens(always_chars)},
            "largest_tools": rows[:REPORT_TOP],
            "method": ("Each listed tool serialized as compact MCP JSON, summed; tokens are chars/4, "
                       "not billed tokens. Excludes server instructions and tool results."),
            "tips": _tips(profile, listed),
        }


def _dump(tool: Any) -> str:
    if hasattr(tool, "model_dump_json"):
        return tool.model_dump_json(by_alias=True, exclude_none=True)
    return json.dumps(tool, ensure_ascii=False, separators=(",", ":"))


def _tokens(chars: int) -> int:
    return round(chars / 4)


def _tips(profile: str, listed: int) -> list[str]:
    tips = []
    if profile != "core":
        tips.append(
            f"Profile '{profile}' lists {listed} tools. Ask the person to set MCP_REVIT_TOOL_PROFILE=core "
            "and restart for a smaller list; search_tools still finds hidden tools."
        )
    tips += [
        "Clients with tool search can defer this server and keep the always_loaded set "
        "(docs/deferred-tool-loading.md).",
        "Take one snapshot_take, then answer multi-element questions with snapshot_compute.",
        "On list reads pass limit, count_only or response_options.fields; in snapshot_compute end with select and limit.",
    ]
    return tips


def _hidden_note(name: str, current: str, profiles: list[str]) -> str:
    if profiles:
        return (
            f"'{name}' is hidden by profile '{current}' and refused if called. Ask the person to set "
            f"MCP_REVIT_TOOL_PROFILE={profiles[0]} and restart the server. Profiles that show it: {', '.join(profiles)}."
        )
    return (
        f"'{name}' is hidden by profile '{current}' and refused if called. No built-in profile shows it; "
        "it needs a custom profile file that includes it."
    )


def _score(tokens: list[str], tool: Any) -> int:
    name = tool.name.lower()
    name_parts = set(name.split("_"))
    desc = tool.description.lower()
    desc_words = set(_words(desc))
    ann = tool.annotations
    flags: set[str] = set()
    if ann is not None:
        if ann.readOnlyHint:
            flags.update({"readonly", "read"})
        else:
            flags.update({"write", "mutating", "modify"})
        if ann.destructiveHint:
            flags.add("destructive")
    score = 0
    joined = "_".join(tokens)
    if joined == name:
        score += 100
    elif joined and joined in name:
        score += 20
    for tok in tokens:
        if tok in name_parts:
            score += 10
        elif tok in name:
            score += 6
        if tok in desc_words:
            score += 3
        elif tok in desc:
            score += 1
        if tok in flags:
            score += 2
    return score
