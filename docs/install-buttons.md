# Install buttons

This page explains how the one-click install links in the README are built. To
regenerate every link, run:

```text
python scripts/make_install_links.py          # print them
python scripts/make_install_links.py --json   # as JSON
python scripts/make_install_links.py --check  # fail if README.md is out of date
```

`packages/mcp-server-revit/tests/test_install_links.py` decodes each link back
to JSON and compares it with the server entry below.

## The server entry

Same shape as an `mcpServers` entry in `claude_desktop_config.json`. No
directory variables are needed: the workspace defaults to
`~/Documents/AEC Model Bridge`.

```json
{"command":"uvx","args":["--from","git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit","aec-model-bridge"],"env":{"MCP_REVIT_MODE":"bridge"}}
```

## VS Code

Official format ([VS Code MCP extension guide](https://code.visualstudio.com/api/extension-guides/ai/mcp)):
`vscode:mcp/install?` followed by `encodeURIComponent(JSON.stringify({name, ...server}))`.
Insiders uses `vscode-insiders:mcp/install?`. It can be opened from a browser
address bar or from a shell.

```text
vscode:mcp/install?%7B%22name%22%3A%22aec-model-bridge%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22git%2Bhttps%3A%2F%2Fgithub.com%2FSam-AEC%2Faec-model-bridge%23subdirectory%3Dpackages%2Fmcp-server-revit%22%2C%22aec-model-bridge%22%5D%2C%22env%22%3A%7B%22MCP_REVIT_MODE%22%3A%22bridge%22%7D%7D
```

Command-line alternative, documented in the
[VS Code MCP servers guide](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
(bash or cmd quoting):

```text
code --add-mcp "{\"name\":\"aec-model-bridge\",\"command\":\"uvx\",\"args\":[\"--from\",\"git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit\",\"aec-model-bridge\"],\"env\":{\"MCP_REVIT_MODE\":\"bridge\"}}"
```

Why the README badge points here and not straight at the link: GitHub removes
`vscode:` and `cursor:` hrefs from rendered Markdown. The usual workaround is
the `https://vscode.dev/redirect/mcp/install?name=...&config=<encoded JSON>`
redirect (also `insiders.vscode.dev`), which answers 302 to the `vscode:` link.
That form is not in the official docs. For this server it does not work: when
tested, vscode.dev's firewall returned HTTP 403 for any value containing
`https://...#subdirectory=...`. Publishing the package to PyPI would allow a
plain `uvx aec-model-bridge` entry and a working redirect button.

## Cursor

Format ([Cursor deeplinks](https://docs.cursor.com/deeplinks)):

```text
cursor://anysphere.cursor-deeplink/mcp/install?name=<name>&config=<base64 of JSON.stringify(server)>
```

`config` is the server entry above, without `name`, base64-encoded (and
percent-encoded in the URL).

```text
cursor://anysphere.cursor-deeplink/mcp/install?name=aec-model-bridge&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL1NhbS1BRUMvYWVjLW1vZGVsLWJyaWRnZSNzdWJkaXJlY3Rvcnk9cGFja2FnZXMvbWNwLXNlcnZlci1yZXZpdCIsImFlYy1tb2RlbC1icmlkZ2UiXSwiZW52Ijp7Ik1DUF9SRVZJVF9NT0RFIjoiYnJpZGdlIn19
```

The README badge uses the https form that other MCP projects use because
GitHub strips `cursor:` links:
`https://cursor.com/en/install-mcp?name=<name>&config=<same base64>`. That
https form is UNVERIFIED. It is not in the Cursor docs, and it could not be
reached from the machine used to build it. Open the button once in a browser
to check it.

## Claude Desktop

The release workflow attaches a `.mcpb` bundle named with the version, so the
README links to `https://github.com/Sam-AEC/aec-model-bridge/releases/latest`.
