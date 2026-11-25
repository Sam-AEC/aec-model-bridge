"""MCP Apps (extension ``io.modelcontextprotocol/ui``) view for plan review. Read-only.

The server offers one HTML resource, ``ui://aec-model-bridge/plan-review``. Tools that return
a plan (``plan_actions``, ``list_pending_plans``) name it in ``_meta.ui.resourceUri``, so a host
that supports MCP Apps can render the plan inline. Hosts without MCP Apps ignore ``_meta`` and
show the normal text result.

The view cannot approve. It has no approve, reject or execute control and sends no
``tools/call``: its only messages to the host are the ``ui/initialize`` handshake and size
notifications. Every tool that is not read-only carries ``_meta.ui.visibility: ["model"]``,
which tells the host to refuse a ``tools/call`` for it from any app. Approve, reject and
roll back are human-only tools: they are never listed and are refused on every MCP call.

Model text reaches the page only as data: the per-plan resource embeds it as JSON with
``<``, ``>`` and ``&`` escaped, and the script renders it with ``textContent``, never as HTML.
The page loads nothing from the network.

Spec: https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from mcp.types import Resource, ResourceTemplate

from .config import config
from .security.approval import ApprovalGate, validate_plan_id
from .security.audit import redact_data
from .security.plan_review import with_review_aids

EXTENSION_ID = "io.modelcontextprotocol/ui"
MIME = "text/html;profile=mcp-app"
SPEC_VERSION = "2026-01-26"
PLAN_REVIEW_URI = "ui://aec-model-bridge/plan-review"
PLAN_REVIEW_TEMPLATE = "ui://aec-model-bridge/plan-review/{id}"
# Tools whose result is a plan or a list of plans; the host renders them with the view.
PLAN_VIEW_TOOLS = frozenset({"plan_actions", "list_pending_plans"})
# Visibility for every tool that is not read-only: callable by the model, never by an app.
MODEL_ONLY = ["model"]
# Key in a plan tool result's _meta that carries the approval mode in force.
APPROVAL_MODE_META_KEY = "aec-model-bridge/approval_mode"


class AppsResourceError(ValueError):
    """The ui:// URI is unknown or names a plan that is not allowed or not found."""


def enabled() -> bool:
    """MCP_REVIT_MCP_APPS (default on). Off: no ui:// resources and no ``_meta.ui`` on tools."""
    return bool(getattr(config, "mcp_apps", True))


def tool_meta(name: str, read_only: bool) -> dict[str, Any] | None:
    """The ``_meta.ui`` block for one listed tool, or None (read-only tools keep the default)."""
    if not enabled():
        return None
    if name in PLAN_VIEW_TOOLS:
        return {"resourceUri": PLAN_REVIEW_URI, "visibility": list(MODEL_ONLY)}
    if not read_only:
        return {"visibility": list(MODEL_ONLY)}
    return None


def is_read_only(tool: Any) -> bool:
    """Same rule as the result presentation; fails closed (an error counts as a write)."""
    from .tool_metadata import is_read_only_tool

    try:
        return is_read_only_tool(tool.name, tool)
    except Exception:
        return False


def listed_tool(provider_id: str, tool: Any) -> Any:
    """The MCP Tool exactly as tools/list sends it: enriched metadata plus ``_meta.ui``."""
    from .tool_metadata import enrich_tool

    return with_tool_meta(enrich_tool(provider_id, tool), is_read_only(tool))


def result_meta(name: str, gate: ApprovalGate | None) -> dict[str, Any]:
    """Keyword arguments that put the approval mode in a plan tool result's ``_meta``.

    ``_meta`` is not model context; the view reads it. The plan JSON itself is unchanged."""
    if not enabled() or name not in PLAN_VIEW_TOOLS or gate is None:
        return {}
    try:
        mode = gate.approval_mode
    except Exception:
        return {}
    return {"_meta": {APPROVAL_MODE_META_KEY: mode}}


def with_tool_meta(tool: Any, read_only: bool) -> Any:
    """Return ``tool`` (an MCP Tool) with ``_meta.ui`` merged into any existing ``_meta``."""
    ui = tool_meta(tool.name, read_only)
    if ui is None:
        return tool
    meta = dict(tool.meta or {})
    meta["ui"] = ui
    return tool.model_copy(update={"meta": meta})


def resource_meta() -> dict[str, Any]:
    """``_meta.ui`` for the view: no network, no external resources, clipboard for 'copy plan id'."""
    return {"ui": {
        "csp": {"connectDomains": [], "resourceDomains": []},
        "permissions": {"clipboardWrite": {}},
        "prefersBorder": True,
    }}


def list_resources() -> list[Resource]:
    if not enabled():
        return []
    return [Resource(
        uri=PLAN_REVIEW_URI, name="Plan review view", mimeType=MIME, _meta=resource_meta(),
        description="Read-only HTML view of a drafted plan for hosts that support MCP Apps. It cannot approve.",
    )]


def list_resource_templates() -> list[ResourceTemplate]:
    if not enabled():
        return []
    return [ResourceTemplate(
        uriTemplate=PLAN_REVIEW_TEMPLATE, name="Plan review view for one plan", mimeType=MIME,
        description="Read-only HTML view of one plan, data included. It cannot approve.",
    )]


_URI = re.compile(r"ui://aec-model-bridge/plan-review(?:/(?P<plan_id>[^/]+))?")


def read_resource(uri: Any, gate: ApprovalGate) -> tuple[str, dict[str, Any]]:
    """Return (html, _meta) for a ui:// URI, or raise AppsResourceError."""
    if not enabled():
        raise AppsResourceError("MCP Apps views are turned off (MCP_REVIT_MCP_APPS=false).")
    match = _URI.fullmatch(str(uri))
    if not match:
        raise AppsResourceError("Unknown resource URI.")
    plan_id = match.group("plan_id")
    if plan_id is None:
        return render_html(None), resource_meta()
    try:
        plan_id = validate_plan_id(plan_id)
        plan = gate.load_plan(plan_id)
    except Exception as exc:
        raise AppsResourceError(str(exc)) from None
    if plan is None:
        raise AppsResourceError(f"Plan '{plan_id}' was not found.")
    data = {"approval_mode": gate.approval_mode, "plans": [with_review_aids(plan, gate.workspace_dir)]}
    return render_html(data), resource_meta()


def embed_json(value: Any) -> str:
    """JSON safe inside a <script type="application/json"> element: no raw <, > or &."""
    text = json.dumps(redact_data(value), default=str, ensure_ascii=True)
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _sha256(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


_STYLE = """
:root{color-scheme:light dark;--bg:#ffffff;--fg:#1d1d1f;--muted:#5f6368;--line:#d0d4d9;--note:#fff6e0;--warn:#8a5a00}
@media (prefers-color-scheme:dark){:root{--bg:#1e1f22;--fg:#e8eaed;--muted:#a0a4aa;--line:#3c4043;--note:#3a3220;--warn:#f0c060}}
body{margin:0;padding:12px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:16px;margin:0 0 8px}h2{font-size:14px;margin:12px 0 6px}
.plan{border:1px solid var(--line);border-radius:6px;padding:10px;margin-bottom:12px}
.facts{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:0}
.facts dt{color:var(--muted)}.facts dd{margin:0;overflow-wrap:anywhere}
code{font-family:ui-monospace,Consolas,monospace;font-size:13px;overflow-wrap:anywhere}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{color:var(--muted);font-weight:600}
.warn{color:var(--warn)}ul{margin:4px 0;padding-left:20px}
.how{background:var(--note);border-radius:6px;padding:8px 10px;margin-top:10px}
button{font:inherit;padding:2px 8px;margin-left:8px;cursor:pointer}
.muted{color:var(--muted)}
"""

# Plain DOM only: no innerHTML, no eval, no inline handlers, no network, no tools/call.
_SCRIPT = r"""
(function () {
  "use strict";
  var root = document.getElementById("root");
  var nextId = 1;
  var waiting = {};

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }
  function txt(value) {
    if (value === undefined || value === null || value === "") { return "-"; }
    return typeof value === "string" ? value : JSON.stringify(value);
  }
  function send(message) {
    if (window.parent && window.parent !== window) { window.parent.postMessage(message, "*"); }
  }
  function request(method, params) {
    var id = nextId++;
    send({ jsonrpc: "2.0", id: id, method: method, params: params });
    return new Promise(function (resolve) { waiting[id] = resolve; });
  }
  function notify(method, params) { send({ jsonrpc: "2.0", method: method, params: params }); }

  function copyPlanId(planId, button) {
    function done(ok) { button.textContent = ok ? "Copied" : "Select and copy the id"; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(planId).then(function () { done(true); }, function () { done(false); });
    } else { done(false); }
  }

  function fact(list, label, value) {
    list.appendChild(el("dt", null, label));
    var dd = el("dd");
    dd.appendChild(el("code", null, txt(value)));
    list.appendChild(dd);
  }

  function rowsOf(plan) {
    if (plan.preview && Array.isArray(plan.preview.rows)) { return plan.preview.rows; }
    var rows = [];
    (Array.isArray(plan.actions) ? plan.actions : []).forEach(function (a) {
      var args = (a && a.arguments) || {};
      rows.push({ tool: a && a.tool, element_id: args.element_id, unique_id: args.unique_id,
                  parameter: args.parameter_name, before: "(not captured)", after: args });
    });
    return rows;
  }

  function warningsOf(plan) {
    var out = [];
    var review = plan.review || {};
    (Array.isArray(review.warnings) ? review.warnings : []).forEach(function (w) { out.push(txt(w)); });
    (Array.isArray(review.conflicts) ? review.conflicts : []).forEach(function (c) {
      out.push("Conflict on element " + txt(c.element_id) + " " + txt(c.parameter) + ": expected " +
               txt(c.expected_current) + ", found " + txt(c.actual_current) + ".");
    });
    var radius = plan.blast_radius || {};
    if (radius.unidentified_actions) {
      out.push(radius.unidentified_actions + " action(s) name no element, so the element count is a lower bound.");
    }
    if (radius.risk === "high") { out.push("Risk is high: many elements or actions."); }
    if (Array.isArray(plan.skipped) && plan.skipped.length) {
      out.push(plan.skipped.length + " item(s) were skipped when the plan was drafted.");
    }
    if (plan.expired) { out.push("This plan has expired and cannot be approved."); }
    return out;
  }

  function renderPlan(plan, mode) {
    var card = el("section", "plan");
    var id = txt(plan.plan_id);
    var head = el("h1", null, "Plan ");
    head.appendChild(el("code", null, id));
    var copy = el("button", null, "Copy plan id");
    copy.type = "button";
    copy.addEventListener("click", function () { copyPlanId(id, copy); });
    head.appendChild(copy);
    card.appendChild(head);

    var review = plan.review || {};
    if (review.summary) { card.appendChild(el("p", null, review.summary)); }

    var facts = el("dl", "facts");
    var radius = plan.blast_radius || {};
    fact(facts, "State", plan.state);
    fact(facts, "Approval mode", mode);
    fact(facts, "Plan hash", plan.plan_hash);
    fact(facts, "Actions", Array.isArray(plan.actions) ? plan.actions.length : radius.action_count);
    fact(facts, "Elements", radius.element_count);
    fact(facts, "Risk", radius.risk);
    fact(facts, "Created", plan.created_at);
    card.appendChild(facts);

    card.appendChild(el("h2", null, "Changes"));
    var wrap = el("div", "scroll");
    var table = el("table");
    var headRow = el("tr");
    ["Tool", "Element", "UniqueId", "Parameter", "Old value", "New value"].forEach(function (h) {
      headRow.appendChild(el("th", null, h));
    });
    var thead = el("thead");
    thead.appendChild(headRow);
    table.appendChild(thead);
    var body = el("tbody");
    var rows = rowsOf(plan);
    rows.forEach(function (r) {
      var tr = el("tr");
      [r.tool, r.element_id, r.unique_id, r.parameter, r.before, r.after].forEach(function (v) {
        tr.appendChild(el("td", null, txt(v)));
      });
      body.appendChild(tr);
    });
    if (!rows.length) {
      var empty = el("tr");
      empty.appendChild(el("td", "muted", "No actions."));
      body.appendChild(empty);
    }
    table.appendChild(body);
    wrap.appendChild(table);
    card.appendChild(wrap);
    if (plan.preview && plan.preview.rows_omitted) {
      card.appendChild(el("p", "muted", plan.preview.rows_omitted + " more row(s) not shown."));
    }

    var warnings = warningsOf(plan);
    if (warnings.length) {
      card.appendChild(el("h2", "warn", "Warnings"));
      var list = el("ul", "warn");
      warnings.forEach(function (w) { list.appendChild(el("li", null, w)); });
      card.appendChild(list);
    }

    var how = el("div", "how");
    how.appendChild(el("p", null, "This view cannot approve, reject or run a plan."));
    var line = el("p", null, "Approve in the Revit panel (Plans view) or run: ");
    line.appendChild(el("code", null, "aec-model-bridge-approve approve " + id));
    how.appendChild(line);
    card.appendChild(how);
    return card;
  }

  function render(data) {
    while (root.firstChild) { root.removeChild(root.firstChild); }
    if (!data || typeof data !== "object") {
      root.appendChild(el("p", "muted", "No plan to show."));
      return;
    }
    if (data.status === "not_needed") {
      root.appendChild(el("p", null, txt(data.message)));
      return;
    }
    var plans = Array.isArray(data.plans) ? data.plans : (data.plan_id ? [data] : []);
    if (!plans.length) {
      root.appendChild(el("p", "muted", "No pending plans."));
      return;
    }
    plans.forEach(function (p) {
      if (p && typeof p === "object") { root.appendChild(renderPlan(p, data.approval_mode)); }
    });
  }

  function parsed(result) {
    if (result.structuredContent && typeof result.structuredContent === "object") { return result.structuredContent; }
    var items = Array.isArray(result.content) ? result.content : [];
    for (var i = 0; i < items.length; i++) {
      var t = items[i] && items[i].type === "text" ? String(items[i].text) : "";
      var at = t.indexOf("Result:\n");
      try { return JSON.parse(at >= 0 ? t.slice(at + 8) : t); } catch (e) { /* not JSON */ }
    }
    return null;
  }
  function fromToolResult(result) {
    if (!result || typeof result !== "object") { return null; }
    var data = parsed(result);
    var meta = result._meta && typeof result._meta === "object" ? result._meta : {};
    if (data && typeof data === "object" && data.approval_mode === undefined && meta["__MODE_KEY__"] !== undefined) {
      data = Object.assign({}, data, { approval_mode: meta["__MODE_KEY__"] });
    }
    return data;
  }

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent) { return; }
    var msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0") { return; }
    if (msg.id !== undefined && !msg.method && waiting[msg.id]) {
      var resolve = waiting[msg.id];
      delete waiting[msg.id];
      resolve(msg.result);
      return;
    }
    if (msg.method === "ui/notifications/tool-result") {
      render(fromToolResult(msg.params));
    } else if (msg.method === "ui/resource-teardown" && msg.id !== undefined) {
      send({ jsonrpc: "2.0", id: msg.id, result: {} });
    } else if (msg.method === "ping" && msg.id !== undefined) {
      send({ jsonrpc: "2.0", id: msg.id, result: {} });
    }
  });

  var embedded = document.getElementById("plan-data");
  if (embedded) {
    try { render(JSON.parse(embedded.textContent)); } catch (e) { render(null); }
  } else {
    render(null);
  }

  request("ui/initialize", {
    protocolVersion: "__SPEC_VERSION__",
    appInfo: { name: "aec-model-bridge plan review", version: "1" },
    appCapabilities: { availableDisplayModes: ["inline"] }
  }).then(function () {
    notify("ui/notifications/initialized", {});
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        notify("ui/notifications/size-changed", {
          width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight });
      }).observe(document.body);
    }
  });
})();
""".replace("__SPEC_VERSION__", SPEC_VERSION).replace("__MODE_KEY__", APPROVAL_MODE_META_KEY)

# The page allows only its own inline style and script (by hash) and nothing else.
CSP = (
    "default-src 'none'; "
    f"script-src '{_sha256(_SCRIPT)}'; style-src '{_sha256(_STYLE)}'; "
    "img-src 'none'; font-src 'none'; connect-src 'none'; frame-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)


def render_html(data: Any | None) -> str:
    """The view. ``data`` (a plan listing) is embedded as escaped JSON; None gives the empty shell
    that the host fills from the tool result."""
    embedded = (
        f'<script type="application/json" id="plan-data">{embed_json(data)}</script>\n'
        if data is not None else ""
    )
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Plan review</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n"
        '<main id="root"><p>Loading the plan.</p></main>\n'
        f"{embedded}<script>{_SCRIPT}</script>\n</body>\n</html>\n"
    )
