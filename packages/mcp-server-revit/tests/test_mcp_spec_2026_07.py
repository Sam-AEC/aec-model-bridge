"""MCP spec 2026-07-28 spike (ADR 0023, issue #271).

Two parts, neither changes server behaviour:

1. An inventory of the MCP features the server code uses, built from the AST of
   every module under ``src/``. It fails when a deprecated feature (Logging,
   Roots, Sampling, HTTP+SSE) appears outside the allowlist in ADR 0023, when an
   allowlist entry goes stale, or when a feature appears that the ADR does not name.
2. Protocol version negotiation with the SDK in-memory streams: ``initialize``
   for every handshake version the installed SDK supports, the answer to a
   ``2026-07-28`` offer, and the legacy fallback a dual-era client takes after
   probing with ``server/discover``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
import mcp.types as mcp_types  # noqa: E402

PKG = Path(__file__).resolve().parents[1]
SRC = PKG / "src"
ADR = PKG.parents[1] / "docs" / "adr" / "0023-mcp-spec-2026-07.md"

MODERN_VERSION = "2026-07-28"

# Markers per feature. "imports": module prefixes; "names": bare names or
# imported symbols; "attrs": attribute names (methods, decorators);
# "keywords": call keyword names; "strings": exact MCP method strings or dict keys.
FEATURES: dict[str, dict[str, set[str]]] = {
    "tools": {"attrs": {"list_tools", "call_tool"}, "names": {"Tool", "CallToolResult"}},
    "tool_annotations": {
        "names": {"ToolAnnotations"},
        "attrs": {"readOnlyHint", "destructiveHint", "read_only_hint", "destructive_hint"},
        "strings": {"readOnlyHint", "destructiveHint"},
    },
    "structured_output": {"keywords": {"structuredContent", "structured_content", "outputSchema"}},
    "server_instructions": {"keywords": {"instructions"}, "strings": {"instructions"}},
    "prompts": {"attrs": {"list_prompts", "get_prompt"}, "names": {"Prompt", "GetPromptResult"}},
    "resources": {
        "attrs": {"list_resources", "read_resource", "list_resource_templates"},
        "names": {"Resource", "ResourceTemplate", "ReadResourceContents"},
    },
    "resource_subscriptions": {
        "attrs": {"subscribe_resource", "unsubscribe_resource", "send_resource_updated"},
        "strings": {"resources/subscribe", "resources/unsubscribe"},
    },
    "list_changed_notifications": {
        "attrs": {"send_tool_list_changed", "send_prompt_list_changed", "send_resource_list_changed"},
    },
    "completions": {"attrs": {"completion"}, "names": {"Completion", "CompleteResult"}, "strings": {"completion/complete"}},
    "elicitation": {"attrs": {"elicit", "elicit_form", "elicit_url"}, "keywords": {"elicitation_callback"}, "strings": {"elicitation/create"}},
    "progress": {"attrs": {"send_progress_notification", "report_progress"}, "strings": {"notifications/progress"}},
    "ping": {"attrs": {"send_ping"}, "strings": {"ping"}},
    "tasks": {
        "imports": {"mcp.server.experimental", "mcp.shared.experimental", "mcp.client.experimental"},
        "names": {"TasksCapability", "CreateTaskResult"},
        "strings": {"tasks/get", "tasks/result", "tasks/list", "tasks/cancel"},
    },
    # Deprecated in 2026-07-28 (SEP-2577, SEP-2596).
    "logging": {
        "attrs": {"send_log_message", "set_logging_level"},
        "keywords": {"logging_callback"},
        "names": {"LoggingMessageNotification", "SetLevelRequest"},
        "strings": {"logging/setLevel", "notifications/message"},
    },
    "roots": {
        "attrs": {"list_roots"},
        "keywords": {"list_roots_callback"},
        "names": {"ListRootsResult", "Root"},
        "strings": {"roots/list", "notifications/roots/list_changed"},
    },
    "sampling": {
        "attrs": {"create_message"},
        "keywords": {"sampling_callback"},
        "names": {"CreateMessageRequest", "CreateMessageResult", "SamplingMessage"},
        "strings": {"sampling/createMessage"},
    },
    "http_sse_transport": {
        "imports": {"mcp.client.sse", "mcp.server.sse"},
        "names": {"sse_client", "SseServerTransport"},
    },
}

DEPRECATED = {"logging", "roots", "sampling", "http_sse_transport"}

# Must match the "Deprecated-feature allowlist" table in ADR 0023.
DEPRECATED_ALLOWLIST: dict[str, set[str]] = {
    "http_sse_transport": {"src/revit_mcp_server/providers/proxy.py"},
}


def _markers(tree: ast.AST) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {k: set() for k in ("imports", "names", "attrs", "keywords", "strings")}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found["imports"].add(node.module)
            for alias in node.names:
                found["imports"].add(f"{node.module}.{alias.name}")
                found["names"].add(alias.name)
        elif isinstance(node, ast.Import):
            found["imports"].update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            found["names"].add(node.id)
        elif isinstance(node, ast.Attribute):
            found["attrs"].add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            found["keywords"].add(node.arg)
        elif isinstance(node, ast.Dict):
            found["strings"].update(
                k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
            )
        elif isinstance(node, ast.Compare | ast.Call):
            # MCP method strings compared against or passed as arguments.
            parts = [*node.comparators, node.left] if isinstance(node, ast.Compare) else node.args
            found["strings"].update(
                p.value for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, str)
            )
    return found


def _uses_mcp(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "mcp":
            return True
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "mcp" for a in node.names):
            return True
    return False


def features_in_source(source: str, *, require_mcp_import: bool = True) -> set[str]:
    tree = ast.parse(source)
    # Server-only features (instructions, list handlers) are recognised in modules
    # that import the SDK; the MCP-layer helpers that build SDK types do too.
    if require_mcp_import and not _uses_mcp(tree):
        return set()
    found = _markers(tree)
    hits = set()
    for feature, markers in FEATURES.items():
        for kind, values in markers.items():
            pool = found[kind]
            if kind == "imports":
                if any(i == v or i.startswith(v + ".") for i in pool for v in values):
                    hits.add(feature)
            elif pool & values:
                hits.add(feature)
    return hits


def inventory() -> dict[str, set[str]]:
    """feature id -> set of files (relative to the package) that use it."""
    result: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        for feature in features_in_source(path.read_text(encoding="utf-8")):
            result.setdefault(feature, set()).add(rel)
    return result


def _adr_text() -> str:
    return ADR.read_text(encoding="utf-8")


def _adr_section(title: str) -> str:
    text = _adr_text()
    match = re.search(rf"^#+ {re.escape(title)}\n(.*?)(?=^#+ )", text, re.S | re.M)
    assert match, f"ADR 0023 has no section {title!r}"
    return match.group(1)


# --- inventory ---------------------------------------------------------------


def test_scanner_detects_deprecated_features_in_a_sample() -> None:
    sample = (
        "from mcp.client.sse import sse_client\n"
        "async def handler(ctx):\n"
        "    await ctx.session.send_log_message(level='info', data='x')\n"
        "    await ctx.session.list_roots()\n"
        "    await ctx.session.create_message(messages=[], max_tokens=1)\n"
    )
    assert features_in_source(sample) >= DEPRECATED


def test_scanner_ignores_modules_without_the_sdk() -> None:
    assert features_in_source("logger.info('list_roots')\nx.create_message()\n") == set()


def test_inventory_finds_the_features_the_server_is_known_to_use() -> None:
    found = inventory()
    for feature in ("tools", "tool_annotations", "structured_output", "server_instructions", "prompts", "resources"):
        assert feature in found, f"scanner no longer sees {feature}; check FEATURES markers"
    assert "src/revit_mcp_server/mcp_server.py" in found["tools"]


def test_no_deprecated_feature_outside_the_allowlist() -> None:
    found = inventory()
    unexpected = sorted(
        f"{feature}: {path}"
        for feature in DEPRECATED
        for path in found.get(feature, set())
        if path not in DEPRECATED_ALLOWLIST.get(feature, set())
    )
    assert not unexpected, (
        "Deprecated MCP feature(s) in MCP 2026-07-28 used outside the allowlist in "
        f"docs/adr/0023-mcp-spec-2026-07.md: {unexpected}. Remove the use, or add it to "
        "the ADR allowlist table and DEPRECATED_ALLOWLIST with a reason."
    )


def test_allowlist_entries_are_still_used() -> None:
    found = inventory()
    stale = sorted(
        f"{feature}: {path}"
        for feature, paths in DEPRECATED_ALLOWLIST.items()
        for path in paths
        if path not in found.get(feature, set())
    )
    assert not stale, f"Remove stale allowlist entries from the test and ADR 0023: {stale}"


def test_allowlist_matches_the_adr_table() -> None:
    section = _adr_section("Deprecated-feature allowlist")
    rows = set(re.findall(r"^\| `([a-z_]+)` \| `([^`]+)` \|", section, re.M))
    expected = {(f, p) for f, paths in DEPRECATED_ALLOWLIST.items() for p in paths}
    assert rows == expected
    assert set(DEPRECATED_ALLOWLIST) <= DEPRECATED


def test_every_used_feature_is_named_in_the_adr_inventory() -> None:
    section = _adr_section("MCP features this server uses")
    listed = set(re.findall(r"^\| `([a-z_]+)` \|", section, re.M))
    missing = sorted(set(inventory()) - listed)
    assert not missing, f"Add these features to the inventory table in ADR 0023: {missing}"
    assert listed <= set(FEATURES), f"unknown feature ids in ADR 0023: {sorted(listed - set(FEATURES))}"


# --- protocol version negotiation ---------------------------------------------

try:  # mcp 1.x
    from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS as HANDSHAKE_VERSIONS
except ImportError:  # pragma: no cover - mcp 2.x
    from mcp.types.version import HANDSHAKE_PROTOCOL_VERSIONS as HANDSHAKE_VERSIONS  # type: ignore

SDK_SPEAKS_MODERN = MODERN_VERSION == getattr(mcp_types, "LATEST_PROTOCOL_VERSION", None) or hasattr(
    mcp_types, "DiscoverRequest"
)

# JSON-RPC codes the 2026-07-28 spec reserves for modern errors; a dual-era
# client must not fall back to initialize when it sees one of these.
MODERN_ERROR_CODES = range(-32099, -32019)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("MCP_REVIT_MODE", "mock")
    from revit_mcp_server import mcp_server

    return mcp_server.app


async def _exchange(app, requests: list[dict]) -> list:
    """Send raw JSON-RPC requests to the server over in-memory streams; return the replies."""
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp.shared.message import SessionMessage

    replies = []
    async with create_client_server_memory_streams() as ((c_read, c_write), (s_read, s_write)):
        async with anyio.create_task_group() as tg:
            tg.start_soon(app.run, s_read, s_write, app.create_initialization_options())
            for i, req in enumerate(requests, start=1):
                message = mcp_types.JSONRPCRequest(jsonrpc="2.0", id=i, **req)
                await c_write.send(SessionMessage(mcp_types.JSONRPCMessage(message)))
                with anyio.fail_after(10):
                    reply = await c_read.receive()
                replies.append(reply.message.root)
            tg.cancel_scope.cancel()
    return replies


def _initialize(version: str) -> dict:
    return {
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "spec-spike", "version": "0"},
        },
    }


@pytest.mark.anyio
@pytest.mark.parametrize("version", list(HANDSHAKE_VERSIONS))
async def test_initialize_answers_every_handshake_version(app, version: str) -> None:
    (reply,) = await _exchange(app, [_initialize(version)])
    result = reply.result
    assert result["protocolVersion"] == version
    assert result["serverInfo"]["name"] == "aec-model-bridge"
    assert "plan_actions" in result.get("instructions", "")
    caps = result["capabilities"]
    assert {"tools", "prompts", "resources"} <= set(caps)
    # ADR 0023: no deprecated capability is advertised.
    assert not caps.get("logging")


@pytest.mark.anyio
async def test_initialize_offering_2026_07_28_gets_a_handshake_version(app) -> None:
    (reply,) = await _exchange(app, [_initialize(MODERN_VERSION)])
    negotiated = reply.result["protocolVersion"]
    assert negotiated in HANDSHAKE_VERSIONS
    if not SDK_SPEAKS_MODERN:
        assert negotiated == max(HANDSHAKE_VERSIONS)


@pytest.mark.anyio
async def test_discover_probe_lets_a_dual_era_client_fall_back(app) -> None:
    if SDK_SPEAKS_MODERN:
        pytest.skip("SDK speaks 2026-07-28: replace with the dual-version test in ADR 0023 step 4")
    probe = {
        "method": "server/discover",
        "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": MODERN_VERSION}},
    }
    discover, init = await _exchange(app, [probe, _initialize(max(HANDSHAKE_VERSIONS))])
    assert isinstance(discover, mcp_types.JSONRPCError), "a legacy server must answer the probe with an error"
    assert discover.error.code not in MODERN_ERROR_CODES
    assert isinstance(init, mcp_types.JSONRPCResponse)
    assert init.result["protocolVersion"] == max(HANDSHAKE_VERSIONS)

