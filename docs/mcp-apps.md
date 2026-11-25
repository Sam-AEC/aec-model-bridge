# MCP Apps plan review view

The server offers a read-only HTML view of a drafted plan for AI clients that support MCP Apps. The client shows it inline next to the tool result. The view cannot approve, reject or run a plan. A person still approves in the Revit panel (Plans view) or with `aec-model-bridge-approve approve <plan_id>`.

## Extension

MCP Apps is the MCP extension `io.modelcontextprotocol/ui`, stable spec version `2026-01-26`. Sources:

- Spec: [ext-apps `specification/2026-01-26/apps.mdx`](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)
- Repository and SDK (`@modelcontextprotocol/ext-apps`): [github.com/modelcontextprotocol/ext-apps](https://github.com/modelcontextprotocol/ext-apps)
- Client list: [modelcontextprotocol.io/extensions/client-matrix](https://modelcontextprotocol.io/extensions/client-matrix)

## When the server sends `_meta.ui`

The spec says a server should add `_meta.ui` only for a client that declared the extension. A client declares it at initialize:

```json
{"capabilities": {"extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}}}
```

`MCP_REVIT_MCP_APPS` sets the mode:

| Value | `_meta.ui` on tools and plan results | `ui://` resources |
| --- | --- | --- |
| `auto` (default) | Only for a client that declared `io.modelcontextprotocol/ui` in `capabilities.extensions`. A `mimeTypes` list, when sent, must contain `text/html;profile=mcp-app`. | Listed and readable. |
| `always` | For every client. | Listed and readable. |
| `off` | Never. | Not listed; reads are refused. |

The server reads the declaration from the session's initialize params on each `tools/list` and `tools/call`, so each client gets its own answer. Nothing is cached across sessions. A declaration under `capabilities.experimental` does not count. `true` and `false` from older configs still work and mean `auto` and `off`. Any other value stops the server at startup with a plain error.

## What the server sends

| Item | Value |
| --- | --- |
| Resource | `ui://aec-model-bridge/plan-review`, MIME type `text/html;profile=mcp-app`. An empty view that the client fills from the tool result. |
| Resource template | `ui://aec-model-bridge/plan-review/{id}`: the same view with one plan embedded, for clients that read resources directly. A pending or approved plan past its expiry is shown with state `expired` and the expiry reason, and without approval instructions. |
| Resource `_meta.ui` | `csp.connectDomains: []`, `csp.resourceDomains: []` (no network, no external files), `permissions.clipboardWrite: {}` (for "Copy plan id"), `prefersBorder: true`. |
| `plan_actions`, `list_pending_plans` | `_meta.ui = {"resourceUri": "ui://aec-model-bridge/plan-review", "visibility": ["model"]}`. |
| Every other tool that is not read-only | `_meta.ui = {"visibility": ["model"]}`. |
| Read-only tools | No `_meta.ui`; the spec default applies. |
| Plan results | A successful `plan_actions` or `list_pending_plans` result carries `_meta["aec-model-bridge/approval_mode"]`, the mode in force. The spec says result `_meta` is not meant for model context. The plan JSON is unchanged. |

The table shows what a client that gets `_meta.ui` sees. Clients without MCP Apps get no `_meta.ui` in `auto` mode, and ignore it in `always` mode, and show the normal text result. That text holds the full plan JSON and `preview_markdown`, a before and after table. For a client that gets `_meta.ui`, `tools/list` grows by about 1,745 tokens ([MCP token budget](mcp-token-budget.md)).

## What the view shows

For each plan: plan id with a "Copy plan id" button, state, approval mode, plan hash, action and element counts, risk, the review summary, a table of changes (tool, element id, UniqueId, parameter, old value, new value) and warnings. Warnings come from `review.warnings`, `review.conflicts`, actions that name no element, high risk, skipped items and expiry. A fixed note says the view cannot approve and gives the panel and command-line steps.

### 3D outlines

The per-plan resource (`ui://aec-model-bridge/plan-review/{id}`) adds an "Affected elements in 3D" section when the plan's snapshot holds a bounding box (`bbox.min`, `bbox.max`) for an element the plan names. Elements are matched by element id or unique id. The section is a wireframe of those boxes on a canvas, turned by dragging, plus a table of element, category, name and size. It shows where the elements are, not a before and after of their shape: the plan actions change values, and the snapshot holds one state. Boxes are drawn in the units the snapshot holds, with no conversion. The section lists up to 200 boxes, counts the rest, and says how many named elements have no box. A plan with no readable snapshot or no valid box shows no 3D section, and nothing is guessed. The boxes are computed when the page is read, are not stored on the plan, and do not change the plan hash. Plan tool results (`plan_actions`, `list_pending_plans`) do not carry them. The section adds no control and no message to the host. Drawing in each MCP Apps client is UNVERIFIED.

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
- Embedded data passes through the same redaction as tool results: paths and secrets always, personal data such as email addresses at the level set by `MCP_REVIT_REDACT_RESPONSES`.

## Configuration

`MCP_REVIT_MCP_APPS`: `auto` (default), `always` or `off`, as in the table above. Read at startup.

## Client support

| Client | Status |
| --- | --- |
| Claude (claude.ai, Claude Desktop) | UNVERIFIED |
| ChatGPT | UNVERIFIED |
| VS Code (GitHub Copilot) | UNVERIFIED |
| Goose | UNVERIFIED |
| Claude Code, Codex, Cursor, Cline | UNVERIFIED; text result only expected |

The ext-apps README lists Claude, ChatGPT, VS Code, Goose, Postman and MCPJam as MCP Apps clients. None of them has been tested with this server. Which of them send the `capabilities.extensions` declaration that `auto` mode needs is also UNVERIFIED; with a client that does not send it, set `MCP_REVIT_MCP_APPS=always`. The tests use the MCP Python SDK in-memory client (`mcp` 1.30) with and without the declaration. The view was rendered in headless Chrome with a test page that plays the client side of the handshake (`ui/initialize`, then `ui/notifications/tool-result`). The CSP meta tag may conflict with a client that injects its own script into the view; UNVERIFIED.
