# Compatibility

AEC Model Bridge is a standard MCP server. It speaks the Model Context Protocol over stdio, so any AI client that can start a local MCP server can use it with the Revit model you have open.

This page separates what is documented and set up in this repository from what should work because it is standard MCP. Nothing marked "not tested" has been tried by the maintainers.

## AI assistants and MCP clients

| Client | Status | How to connect |
| --- | --- | --- |
| Claude Desktop | Documented here | Install the `.mcpb` bundle from the [latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest), or tick the Claude Desktop option in the installer. The README shows the `claude_desktop_config.json` entry. |
| VS Code with GitHub Copilot (agent mode) | Documented here | Use the [VS Code extension](../extensions/vscode/README.md), the committed [`.vscode/mcp.json`](../.vscode/mcp.json), or the install link in [install-buttons.md](install-buttons.md). |
| Cursor | Documented here | Use the Cursor install link in the README, or add the `mcpServers` entry from the README. |
| Codex | Documented here | The README states Codex uses the same values as the Claude Desktop entry. The panel chat can also call the `codex` command-line tool. |
| Hermes Desktop | Example provided | Start from [`docs/examples/hermes-desktop.json`](examples/hermes-desktop.json). |
| Windsurf, Cline, Roo Code, Continue | Same configuration shape, not tested | [marketplaces.md](marketplaces.md) lists these as accepting the `mcpServers` entry. |
| Claude Code, Zed, Gemini CLI, Goose, LM Studio, JetBrains AI Assistant | Standard MCP clients, not tested | They can start a stdio MCP server. Use the same command, arguments and environment variables as the README entry. Check each client's own MCP documentation for where the entry goes. |

## Agent frameworks

Any framework with an MCP stdio client can launch the server and call its tools. Examples are the Claude Agent SDK, the OpenAI Agents SDK, and LangChain or LangGraph through an MCP adapter. None of these has been tested with this server.

## What will not work directly

A client that only accepts a remote MCP server over HTTP cannot start a local stdio server. That includes many browser-based chat apps. A local proxy that exposes a stdio server over HTTP can bridge the gap, but you would be opening the model to whatever can reach that proxy, so read [Security](security.md) first. The server is designed for a single machine, with the Revit add-in on loopback.

The Revit add-in is always required for live work. The server talks to a running copy of Revit on Windows.

## Applications and formats

| Tool | Status | Notes |
| --- | --- | --- |
| Revit 2024 to 2027 | Available | Native C# add-in. |
| IFC | Available | Reads IFC files without Revit running. |
| Rhino and Grasshopper | Available | Connects to the Rhino add-in on `localhost:3004`. |
| Speckle | Available | Needs a Speckle client ID in your environment. |
| Navisworks Manage | In progress | The provider and tools are registered. The add-in is not finished. |
| Power BI | In progress | The tool exists but is not registered in the hub. |
| Excel and SQLite | Available as export | The report tools write `.xlsx` and `.db` files. |

## Where the server is listed

Registry files for the official MCP Registry (`server.json`), Smithery (`smithery.yaml`, mock mode) and Glama (`glama.json`) are in the repository root. See [marketplaces.md](marketplaces.md) for the current status of each listing.

## Try it without Revit

Set `MCP_REVIT_MODE` to `mock` and any client above can browse the tools and get sample answers. Mock data is never used in live mode.
