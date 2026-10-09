# Documentation index

Start with the [installation guide](install.md). The main [README](../README.md) covers what the project is and how to connect a client.

## Guides and reference

- [install.md](install.md): install the Revit add-in and the MCP server.
- [VS Code extension](../extensions/vscode/README.md): build and install the extension locally.
- [configuration-reference.md](configuration-reference.md): environment variables, package metadata and runtime settings.
- [tools-generated.md](tools-generated.md): the tool catalog, generated from the server (do not edit by hand).
- [security.md](security.md): trust boundaries, workspace sandboxing and enterprise hardening.
- [logging-and-audit.md](logging-and-audit.md): Python-side audit log and add-in logging.
- [marketplaces.md](marketplaces.md): MCP Registry, bundle and client distribution.
- [versioning.md](versioning.md): version numbers, release tags and release assets.
- [roadmap.md](roadmap.md): coordinator workflows, demo scope and the next fixes.

## For contributors

- [module-authoring.md](module-authoring.md): write a plugin module (commands, schemas, QA rules).
- [build-and-install-scripts.md](build-and-install-scripts.md): what each script in `scripts/` does.
- [target-frameworks-and-dependencies.md](target-frameworks-and-dependencies.md): Python and .NET targets per component.
- [revit-addin-lifecycle.md](revit-addin-lifecycle.md): how the Revit add-in starts up and runs commands.
- [design/tokens.md](design/tokens.md): design tokens for the add-in and panel UI ([design/review.html](design/review.html) is the visual review page).
- [design/readme-visual-brief.md](design/readme-visual-brief.md): Claude Design prompt for README images and a demo cover.
- [release-retirement.md](release-retirement.md): reviewed release inventory and future cleanup procedure.
- [examples/hermes-desktop.json](examples/hermes-desktop.json): sample client config for Hermes Desktop.

## Architecture decision records

- [0001](0001-multi-provider-architecture.md): multi-provider automation architecture.
- [0002](0002-switch-contract-v2.md): switch contract v2.
- [0007](0007-hub-performance-posture.md): hub performance posture.
- [0008](0008-approval-gate-lifecycle.md): approval gate and action plan lifecycle.
- [0009](0009-plugin-module-system.md): plugin module system.
- [0010](0010-snapshot-schema.md): semantic BIM snapshot and delta schema.
- [0011](0011-panel-architecture.md): WebView2 dockable panel and hub message bridge.
- [0012](0012-native-agent-chat-backend.md): native tool-calling loop for chat.

Numbers 0003 to 0006 are not in this repository.

## Diagrams

- [diagrams/](diagrams/): Mermaid sources for the architecture and approval-flow diagrams in the README. [images/](images/) holds the rendered light and dark PNGs; regenerate them with `scripts/render_diagrams.py`.
