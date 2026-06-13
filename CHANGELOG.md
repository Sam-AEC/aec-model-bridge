# Changelog

## 1.2.0 - 2026-06-13

- Implement Phase B Switch Contract v2 with ADR 0002 specification.
- Add hub discovery registry reader and bearer-token client with legacy fallback.
- Enhance Revit add-in with Contract v2 runtime, token generation, and capability manifest generation via reflection.
- Introduce Navisworks command routing infrastructure with attribute-based registry.
- Establish baseline hub performance posture with ADR 0007.
- Add parameterized provider contract tests and automated tool catalog generation.
- Implement SQLiteExporterProvider for local database exports and graph mapping.
- Add multi-provider integration, persistent background event loop, and data redaction.
- Perform repository hygiene by removing obsolete agent task files and temporary branches.

## 1.1.0 - 2026-06-11

- Rewrite the README as a shorter product and installation guide.
- Standardize public badges on the Shields.io `flat-square` style.
- Remove the custom download dashboard and repository-owned metric assets.
- Clarify installation for Revit 2024, 2025, 2026, and 2027.
- Adopt a GPL-3.0-or-later and commercial dual-licensing model for version
  1.1.0 and later, with a narrow Revit linking exception.
- Add 16x16 and 32x32 theme-aware ribbon icons and maintainer profile links
  to the Revit Help and About dialogs.
- Preserve the MIT terms and notices for version 1.0.2 and earlier.

## 1.0.2 - 2026-06-11

- Replace the external star-history chart with repository-owned release-download tracking.
- Add daily total, 7-day, and 30-day download badges with a generated download chart.
- Upgrade the MCPB manifest to the portable `uv` runtime format with guided workspace configuration.
- Add verified repository, GitHub profile, issue tracker, and LinkedIn links to the Revit UI.
- Replace unsupported UI claims with the actual 100 MCP tools and 103 active bridge routes.
- Add an About ribbon command and refine the theme-aware status, help, and configuration dialogs.
- Add continuous Python tests and Revit 2024-2027 add-in builds.
- Correct installer paths, runtime environment names, packaged wheel instructions, and stale documentation links.
- Install add-in binaries by Revit year and remove duplicate legacy manifests so supported versions can coexist.

## 1.0.1 - 2026-06-11

- Add Autodesk Revit 2027 support targeting .NET 10.
- Fix Revit startup failure when ribbon icon files are missing.
- Package all runtime dependencies required by the Revit add-in.
- Align MCP and bridge tool discovery with active implementations.
- Add live download and repository-growth metrics to the README.
- Add reproducible GitHub release packaging and publication automation.
- Rename the public product to AEC Model Bridge and add trademark/API compliance notices.
- Remove Autodesk product artwork and verify release packages exclude Autodesk API assemblies.

## 1.0.0 - 2026-05-27

- Initial 1.0 release.
