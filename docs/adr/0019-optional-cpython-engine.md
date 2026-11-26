# ADR 0019: Optional CPython 3 engine for scripts that need numpy or pandas

## Status

Proposed (issue #45). Not implemented. Nothing here has run in Revit.

## Context

`revit_execute_python` runs IronPython: 2.7 on Revit 2024 (net48) and 3.4 on Revit 2025 and later (net8, net10), from `PythonEngineFactory.cs` and `PythonScriptRunner.cs`. IronPython runs in the Revit process and calls the Revit API directly. It cannot load C extension modules, so numpy, pandas, scipy and shapely do not work. Users ask for these for clustering, statistics, tabular reports and geometry checks.

Constraints that any engine must keep:

- The Revit API may only be called on Revit's main thread, inside an API context (an `IExternalEventHandler` callback or a command). The add-in already queues every bridge request onto that thread (`CommandQueue.cs`, `ExternalEventHandler.cs`).
- A script cannot be cancelled once it runs on that thread. Long work blocks Revit's user interface.
- Read mode and the approval gate stay as they are: `mode='read'` refuses transaction text on the server and in the add-in and runs inside a transaction group that is always rolled back; `mode='write'` needs an approved plan. See [ADR 0008](0008-approval-gate-lifecycle.md) and `security/read_mode.py`.
- The add-in ships for three target frameworks and is installed per user; the installer size matters.

## Options

### A. pythonnet in the Revit process

Embed CPython 3 through pythonnet (Python.Runtime) in the add-in. The script gets `doc` and the Revit API through the .NET bridge, as with IronPython.

- Threading: CPython has a global interpreter lock; pythonnet needs `PythonEngine.Initialize()` once per process and `Py.GIL()` around every call. Initialisation must happen on the Revit thread, or the GIL must be released after initialising (`BeginAllowThreads`) so the Revit thread can take it. A second add-in that also embeds a different CPython (pyRevit with CPython, Dynamo CPython3) conflicts: only one `python3x.dll` can be loaded per process. Dynamo for Revit 2025+ ships its own CPython 3 through pythonnet, so version clashes are likely.
- Safety: the same read-mode text check applies to the script, and the same rolled-back transaction group wraps it. But a CPython script can load arbitrary native code (`ctypes`, compiled wheels), so the read-mode text check covers even less than it does for IronPython; the roll-back guard stays the real protection for the model, and none of it protects the machine.
- Packaging: an embeddable CPython 3.12 is about 10 MB zipped; numpy and pandas add about 60 to 80 MB per Python version. Three target frameworks can share one Python runtime folder.
- Crash risk: a native extension that crashes takes Revit down with the open model.

### B. CPython in a separate process, Revit API only through the bridge

The script runs in a normal CPython process started by the MCP server (or a worker), with numpy and pandas from the user's environment. It does not touch the Revit API. It reads model data through existing read tools or a snapshot (`snapshot_take`, `snapshot_compute`) and writes back only through plans.

- Threading: no Revit thread involvement while the script computes; Revit stays responsive. Data crosses as JSON.
- Safety: writes go through `plan_actions` and `execute_plan` like any other tool. A read-only analysis needs no model access at all. The process runs with the server's file-system limits (workspace sandbox) but is still code execution on the host, so it needs the `python.host` permission and approval rules of its own.
- Packaging: nothing added to the add-in. The server uses the Python it already runs on, or an optional extra (`uv sync --extra analysis`).
- Limit: no direct API calls, so geometry must come from snapshot data or dedicated read commands.

### C. Hybrid: IronPython gathers, CPython computes

An IronPython script (with `helpers: true`) gathers ids and values into a compact table; a server-side CPython step computes on it; a write-mode IronPython script or a plan applies the result. This is B with a documented hand-off.

## Recommendation

Do not embed CPython in the Revit process now. Implement B/C first:

1. A server-side analysis tool that runs CPython code over a snapshot or the output of a read-mode script, with numpy and pandas as an optional extra, no Revit API access, and the host-Python permission (`MCP_REVIT_ALLOW_PYTHON_HOST`) plus approval for anything that writes files.
2. Model changes keep going through IronPython write scripts or dedicated tools under the approval gate.

Revisit option A only if a concrete use needs direct API calls with numpy in the same script, and after testing coexistence with Dynamo's CPython on Revit 2025 to 2027. If A is built, it must: initialise once per process on the Revit thread, run every script on that thread through the existing queue, keep the read-mode text check and the rolled-back group, refuse to load when another CPython is already in the process, and ship the runtime as a separate optional download.

## Consequences

- No change to the add-in, the read-mode rules or the approval gate.
- Scripts that need numpy split into gather (IronPython, read mode) and compute (CPython, outside Revit) steps.
- The installer size stays as it is.
