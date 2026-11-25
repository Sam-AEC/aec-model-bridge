# MCP Apps plan review view

The server offers a read-only HTML view of a drafted plan for AI clients that support MCP Apps. The client shows it inline next to the tool result. The view cannot approve, reject or run a plan. A person still approves in the Revit panel (Plans view) or with `aec-model-bridge-approve approve <plan_id>`.

## Extension

MCP Apps is the MCP extension `io.modelcontextprotocol/ui`, stable spec version `2026-01-26`. Sources:

- Spec: [ext-apps `specification/2026-01-26/apps.mdx`](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)
- Repository and SDK (`@modelcontextprotocol/ext-apps`): [github.com/modelcontextprotocol/ext-apps](https://github.com/modelcontextprotocol/ext-apps)
- Client list: [modelcontextprotocol.io/extensions/client-matrix](https://modelcontextprotocol.io/extensions/client-matrix)

## What the server sends

| Item | Value |
| --- | --- |
| Resource | `ui://aec-model-bridge/plan-review`, MIME type `text/html;profile=mcp-app`. An empty view that the client fills from the tool result. |
| Resource template | `ui://aec-model-bridge/plan-review/{id}`: the same view with one plan embedded, for clients that read resources directly. |
| Resource `_meta.ui` | `csp.connectDomains: []`, `csp.resourceDomains: []` (no network, no external files), `permissions.clipboardWrite: {}` (for "Copy plan id"), `prefersBorder: true`. |
| `plan_actions`, `list_pending_plans` | `_meta.ui = {"resourceUri": "ui://aec-model-bridge/plan-review", "visibility": ["model"]}`. |
| Every other tool that is not read-only | `_meta.ui = {"visibility": ["model"]}`. |
| Read-only tools | No `_meta.ui`; the spec default applies. |
| Plan results | A successful `plan_actions` or `list_pending_plans` result carries `_meta["aec-model-bridge/approval_mode"]`, the mode in force. The spec says result `_meta` is not meant for model context. The plan JSON is unchanged. |

Clients without MCP Apps ignore `_meta` and show the normal text result. That text holds the full plan JSON and `preview_markdown`, a before and after table. `tools/list` grows by about 1,745 tokens of `_meta` ([MCP token budget](mcp-token-budget.md)).

## What the view shows

For each plan: plan id with a "Copy plan id" button, state, approval mode, plan hash, action and element counts, risk, the review summary, a table of changes (tool, element id, UniqueId, parameter, old value, new value) and warnings. Warnings come from `review.warnings`, `review.conflicts`, actions that name no element, high risk, skipped items and expiry. A fixed note says the view cannot approve and gives the panel and command-line steps.

In Dev mode `plan_actions` drafts no plan; the view shows the `not_needed` message.

## Why the view cannot approve

The AI client controls the view, so it must not become an approval channel.

- The view has no approve, reject, roll back or execute control. Its only button copies the plan id.
- The view sends no `tools/call`, `ui/message` or `ui/open-link`. It sends only `ui/initialize`, `ui/notifications/initialized` and `ui/notifications/size-changed`.
- Every tool that is not read-only, including `plan_actions`, `list_pending_plans` and `execute_plan`, has `visibility: ["model"]`. The spec says the client must refuse a `tools/call` from a view for such a tool.
- `approve_plan`, `reject_plan` and `rollback_plan` are human-only. They are not listed and every MCP tool call to them is refused with kind `human_only`, whoever sends it.
- `tests/test_mcp_apps.py` checks each of these points.

## Security of the page

- Self-contained: inline style and script only, no fonts, images, links, frames or network calls.
- A `Content-Security-Policy` meta tag allows only the page's own inline style and script by SHA-256 hash. `default-src`, `connect-src`, `frame-src`, `object-src`, `base-uri` and `form-action` are `'none'`. No `unsafe-inline` or `unsafe-eval`.
- Model text is data. The per-plan resource embeds the plan as JSON with `<`, `>` and `&` escaped as `<`, `>` and `&`. The script writes all text with `textContent`, never as HTML.
- Embedded data passes through the same redaction as tool results (paths, secrets).

## Configuration

`MCP_REVIT_MCP_APPS` (default `true`). Set `false` to stop listing the `ui://` resources, refuse reads of them and leave `_meta.ui` off every tool. Read at startup.

## Client support

| Client | Status |
| --- | --- |
| Claude (claude.ai, Claude Desktop) | UNVERIFIED |
| ChatGPT | UNVERIFIED |
| VS Code (GitHub Copilot) | UNVERIFIED |
| Goose | UNVERIFIED |
| Claude Code, Codex, Cursor, Cline | UNVERIFIED; text result only expected |

The ext-apps README lists Claude, ChatGPT, VS Code, Goose, Postman and MCPJam as MCP Apps clients. None of them has been tested with this server. The view was rendered in headless Chrome with a test page that plays the client side of the handshake (`ui/initialize`, then `ui/notifications/tool-result`). The CSP meta tag may conflict with a client that injects its own script into the view; UNVERIFIED.
