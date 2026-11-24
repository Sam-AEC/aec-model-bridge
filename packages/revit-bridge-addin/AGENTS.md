# AGENTS.md: packages/revit-bridge-addin

Root `AGENTS.md` applies. This file lists what differs here.

## Environment
C# add-in for Revit 2024 (net48), 2025 and 2026 (net8.0-windows), 2027 (net10.0-windows). It builds on Windows only. Do not try to build or run it in a Linux container; edit carefully and say the change is unbuilt.

## Commands (Windows, PowerShell)
```powershell
.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release
dotnet test packages/revit-bridge-addin-tests -c Release -p:RevitVersion=2026
.\scripts\assert-no-autodesk-assemblies.ps1
```
Without Revit installed, the build uses the Revit API reference packages.

## Traps
- Revit API calls run on the single UI thread through `src/Bridge/CommandQueue.cs` and an `ExternalEvent`. Never call the API from a request thread.
- The HTTP bridge gives up after 30 s but Revit keeps executing. Keep commands short and bounded.
- Writes use `BridgeTransaction`. Do not add `CreateTransaction` recursion (it crashed Revit before, #95).
- Never commit or package Autodesk assemblies. `NoAutodesk*` tests and the assert script enforce this.
- `revit_execute_python` runs IronPython 2.7: no standard library, no `out` parameter marshalling.
- Add a bridge command with `[BridgeCommand]` in `src/Bridge/`, then add the matching Python tool and test in `packages/mcp-server-revit`.
- Live behaviour is UNVERIFIED until run in Revit. See `docs/revit-addin-live-validation-2026-10-14.md` for what was checked.
- Installing a new add-in build needs Revit closed (the DLL is locked while loaded).
