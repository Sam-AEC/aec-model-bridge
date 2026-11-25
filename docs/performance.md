# Server start-up and bridge client performance

All numbers on this page are mock-mode measurements of the Python MCP server (`MCP_REVIT_MODE=mock`). No Revit was involved; they do not describe live Revit calls. See [ADR 0007](adr/0007-hub-performance-posture.md) for the performance rules.

## Method

- Linux container, Python 3.13, the project virtual environment, an empty temporary workspace, no APS, Speckle or proxy settings.
- "Before" runs the previous source tree, "after" runs the current one, on the same interpreter and installed packages. Runs alternate between the two; the table shows the median.
- Phase times come from one fresh process per run: import `revit_mcp_server.mcp_server`, call `build_registry()`, call `list_tools()` once.
- "Spawn to list_tools" starts `python -m revit_mcp_server` over stdio with the MCP Python client, sends `initialize`, then `tools/list`, and stops the clock at the reply.
- Absolute numbers depend on the machine. Compare the before and after columns only.
- The table was measured on an idle machine with the 1.5.1 tree as "before". A repeat with the 1.6 tree as "before" on a loaded machine showed the same direction: spawn to `tools/list` 1,326 ms to 856 ms, `build_registry()` 589 ms to 65 ms (medians).

## Cold start (mock mode)

| Measure (median) | Before | After |
| --- | ---: | ---: |
| Spawn to `tools/list` reply, stdio (9 runs) | 825 ms | 575 ms |
| Import `revit_mcp_server.mcp_server` (11 runs) | 449 ms | 426 ms |
| `build_registry()` | 231 ms | 38 ms |
| First `list_tools()` | 8 ms | 11 ms |
| Whole process, import to first `list_tools()` | 912 ms | 632 ms |
| Modules loaded after `list_tools()` | 1,040 | 711 |

## What changed

- `openpyxl` (which loads `numpy`) is imported by `report_generator` only when a tool writes a workbook. `param_completeness` loads `report_generator` at start, so this import ran on every start before.
- `yaml` is imported by `qaqc_checker` and `recipe_runner` only when a rule pack or recipe is read.
- The Speckle and Autodesk Data providers build their `httpx.AsyncClient` on first request. Each client loads the system CA bundle (about 10 ms), and three were built at start.
- The module registry reads the installed package version once instead of once per module (32 metadata file parses).

`specklepy`, `ifcopenshell` and `networkx` were already lazy. Tests check that importing the server and building the registry load none of `specklepy`, `ifcopenshell`, `networkx`, `openpyxl`, `numpy` or `yaml`, and build no `httpx.AsyncClient` (`tests/test_lazy_imports_and_client_reuse.py`).

## What remains

- About 420 ms of the import is the MCP Python SDK itself (`mcp.server` loads FastMCP, Starlette, Uvicorn, Pydantic and httpx). The server cannot skip it.
- The server's own modules add about 60 ms on top of the SDK.

## Result JSON

`orjson` was not added. `json.dumps` of a 200 KB result takes about 2 ms here, and read-only results are capped at 20,000 characters by default (`max_chars`). The gain would not be measurable in a tool call.

## Bridge client

- `BridgeClient` sends `Accept-Encoding: gzip`. httpx decodes a gzip body before `.json()`, so an add-in that compresses large responses needs no other client change. Plain bodies still work.
- Panel hub routing keeps one cached client per Revit (endpoint and session token). Building a client and its network initialise run outside the cache lock. A cached client is dropped when its Revit's registry entry is gone, or after its `/health` probe fails three times in a row following failed calls (`bridge/routing.py`).

## Add-in timings

`revit_perf_report` reads the add-in's `/health` and lists per-command `count`, `p50_ms`, `p95_ms`, `max_ms` and `avg_bytes`, sorted by p95, with `queue_depth`. An add-in without a `timings` field is reported as older, not as an error. In mock mode the tool returns sample numbers marked `mock: true`.

UNVERIFIED: the `timings` field and gzip responses come from a separate add-in change. Neither was observed against a live Revit for this page.
