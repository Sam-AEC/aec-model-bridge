# ADR 0012: Native Anthropic Tool-Calling Loop for Chat

## Status
Accepted

## Context
The chat feature in `agent_bridge.py` currently shells out to the `claude` or `codex` CLI binaries. The module's own docstring states: *"Personal-use scope only: this assumes the operator's own machine has `claude` and/or `codex` on PATH and already authenticated... do not extend this to the general product surface without revisiting that."*

In practice, neither CLI is on PATH on a fresh install, causing chat to fail for every new user with a CLI-not-found error. This blocks the chat feature from being a reliable, out-of-the-box capability for the end product.

## Decisions

### 1. Primary Chat Path: Native Anthropic API Loop
Build a native Anthropic tool-calling loop (`agent_native.py`, added in a later task) as the primary chat path. This loop will:
- Use an API key stored via a new `anthropic_api_key` config field (populated from the environment variable `MCP_REVIT_ANTHROPIC_API_KEY` or a `.env` file)
- Call the Anthropic API directly without any subprocess/CLI dependency
- Invoke provider tools by calling `provider.execute_tool(name, arguments)` directly — the same primitive that `mcp_server.py` and `panel_server.py` already use for tool invocation
- Leverage the existing tool registry (`ProviderTool.name`, `description`, `input_schema` in `providers/base.py`), which already speaks the exact schema Anthropic's tool-use API requires

### 2. Fallback Path: CLI Shelling (Preserved)
Keep the existing `agent_bridge.py` CLI-shelling path as an explicit fallback for power users who have the CLI installed and authenticated. This path is not being removed because it is a real, currently working path for users who prefer it.

### 3. Configuration Surface
The `anthropic_api_key` field is added to the `Config` class (`config.py`). It follows the existing `MCP_REVIT_`-prefixed pydantic-settings pattern, requiring no bespoke settings-loading code — environment variables and `.env` files are auto-discovered by the existing loader.

## Consequences
- **Chat Works Out of the Box**: Users can enable chat with just an API key, eliminating the CLI install/login dependency that blocked adoption
- **No Subprocess/IPC Overhead**: The native loop calls `provider.execute_tool(name, arguments)` directly without subprocess overhead, IPC marshalling, or JSON serialization round-trips
- **Schema Alignment**: The tool registry already holds the exact schema (`name`, `description`, `input_schema`) needed by Anthropic's tool-use API, with no schema translation or adaptation required
- **Backward Compatibility**: The CLI path remains available for users who prefer it or have complex, non-tool-calling workflows
- **Out of Scope**: A native OpenAI/Codex-API loop is explicitly out of scope for now. The `codex` provider option remains CLI-only
