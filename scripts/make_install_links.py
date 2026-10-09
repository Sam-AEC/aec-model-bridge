#!/usr/bin/env python3
"""Print (or verify) the one-click install links for AEC Model Bridge.

Usage:
    python scripts/make_install_links.py          # print every link
    python scripts/make_install_links.py --json   # print as JSON
    python scripts/make_install_links.py --check  # fail if README.md is out of date

How each link is built is documented in docs/install-buttons.md.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from urllib.parse import quote

NAME = "aec-model-bridge"
REPO = "https://github.com/Sam-AEC/aec-model-bridge"
RELEASES_LATEST = f"{REPO}/releases/latest"

# The server entry, same shape as an `mcpServers` entry in claude_desktop_config.json.
SERVER = {
    "command": "uvx",
    "args": [
        "--from",
        f"git+{REPO}#subdirectory=packages/mcp-server-revit",
        "aec-model-bridge",
    ],
    "env": {"MCP_REVIT_MODE": "bridge"},
}


def _compact(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def vscode_deeplink() -> str:
    """vscode:mcp/install?<encodeURIComponent(JSON.stringify({name, ...server}))>"""
    return "vscode:mcp/install?" + quote(_compact({"name": NAME, **SERVER}), safe="")


def vscode_redirect() -> str:
    """https redirect (the form other MCP READMEs use); 302s to the vscode: deeplink.

    NOTE: vscode.dev's firewall answers 403 for this server's
    `...#subdirectory=...` argument, so this link is NOT used in the README.
    Kept for when the server is available without a #subdirectory= URL.
    """
    return (
        f"https://vscode.dev/redirect/mcp/install?name={quote(NAME, safe='')}"
        f"&config={quote(_compact(SERVER), safe='')}"
    )


def vscode_cli() -> str:
    """Documented CLI install: code --add-mcp "<JSON>" (bash/cmd quoting)."""
    escaped = _compact({"name": NAME, **SERVER}).replace('"', '\\"')
    return f'code --add-mcp "{escaped}"'


def _cursor_config() -> str:
    return base64.b64encode(_compact(SERVER).encode("utf-8")).decode("ascii")


def cursor_deeplink() -> str:
    """cursor://anysphere.cursor-deeplink/mcp/install?name=<name>&config=<base64 JSON>"""
    return (
        "cursor://anysphere.cursor-deeplink/mcp/install"
        f"?name={quote(NAME, safe='')}&config={quote(_cursor_config(), safe='')}"
    )


def cursor_web_link() -> str:
    """https link that GitHub keeps (it strips cursor: hrefs)."""
    return (
        f"https://cursor.com/en/install-mcp?name={quote(NAME, safe='')}"
        f"&config={quote(_cursor_config(), safe='')}"
    )


def all_links() -> dict[str, str]:
    return {
        "vscode_deeplink": vscode_deeplink(),
        "vscode_redirect": vscode_redirect(),
        "vscode_cli": vscode_cli(),
        "cursor_deeplink": cursor_deeplink(),
        "cursor_web_link": cursor_web_link(),
        "claude_desktop_bundle": RELEASES_LATEST,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print links as JSON")
    parser.add_argument("--check", action="store_true", help="verify README.md uses the current links")
    args = parser.parse_args(argv)
    links = all_links()
    if args.check:
        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
        stale = [k for k in ("cursor_web_link", "claude_desktop_bundle") if links[k] not in readme]
        if "docs/install-buttons.md#vs-code" not in readme:
            stale.append("vscode_button")
        if stale:
            print("README.md is out of date for: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("README.md install links are current.")
        return 0
    if args.json:
        print(json.dumps(links, indent=2))
    else:
        for key, value in links.items():
            print(f"{key}:\n{value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
