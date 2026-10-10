# Target Frameworks And Dependencies

This repository is intentionally polyglot. The Python MCP server and the Revit add-in do not share the same runtime constraints.

## Python Package

The Python package metadata lives in [packages/mcp-server-revit/pyproject.toml](../packages/mcp-server-revit/pyproject.toml).

Current characteristics:

- package name: `aec-model-bridge`
- Python requirement: `>=3.11`
- validation and settings stack: `pydantic`, `pydantic-settings`
- transport stack: `httpx`
- environment loading: `python-dotenv`
- development and test dependencies are defined inline rather than split into a separate requirements file

Licences of the direct Python dependencies, read from the installed package metadata for the versions in `uv.lock`:

| Package | Locked version | Licence |
|---|---|---|
| `mcp` | 1.28.1 | MIT |
| `ifcopenshell` | 0.8.5 | LGPL-3.0-or-later |
| `specklepy` | 3.2.8 | Apache-2.0 |
| `pydantic` | 2.13.4 | MIT |
| `pydantic-settings` | 2.14.2 | MIT |
| `httpx` | 0.28.1 | BSD License (as named in the package classifiers) |
| `python-dotenv` | 1.2.2 | BSD-3-Clause |
| `networkx` | 3.6.1 | BSD-3-Clause |

The full list, including transitive packages and the NuGet and npm packages, is in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Licences of the NuGet packages named below have not been verified and are left out of this page on purpose.

## Revit Add-in Targets

The add-in project file is [packages/revit-bridge-addin/RevitBridge.csproj](../packages/revit-bridge-addin/RevitBridge.csproj).

It conditionally targets:

- `net48` for Revit 2024
- `net8.0-windows` for Revit 2025 and 2026
- `net10.0-windows` for Revit 2027

That dual-target behavior is one of the most important build facts in the repo.

## Revit API Reference Strategy

The add-in first tries to bind against locally installed Revit assemblies:

- `RevitAPI.dll`
- `RevitAPIUI.dll`

If those are not present, it falls back to NuGet packages:

- `Nice3point.Revit.Api.RevitAPI`
- `Nice3point.Revit.Api.RevitAPIUI`

This makes CI and local developer environments more forgiving, while still supporting direct machine installs with real Autodesk binaries.

## Additional Add-in Dependencies

The C# layer also references:

- `Serilog`
- `Serilog.Sinks.File`
- `System.Text.Json`
- `IronPython` 2.7 on `net48`
- `IronPython` 3.4.1 on the modern .NET targets used by Revit 2025-2027

The conditional IronPython dependency exists because the repo exposes an `execute_python` bridge command.

## Temporary Compile Exclusions

`RevitBridge.csproj` currently removes several command directories from compilation:

- `src\Commands\Core\**\*.cs`
- `src\Commands\Advanced\**\*.cs`
- `src\Commands\Specialized\**\*.cs`
- `src\Commands\Enhancements\**\*.cs`

That means the source tree advertises a broader command surface than the compiled binary necessarily includes at the moment.

## Operational Rule

When a build succeeds locally but not in CI, check target framework and dependency resolution before debugging the business logic. In this repo, version-conditional framework selection is part of normal operation, not an edge case.
