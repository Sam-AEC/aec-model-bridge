"""Decode the one-click install links back to JSON (see docs/install-buttons.md)."""
import base64
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = REPO_ROOT / "scripts" / "make_install_links.py"
_spec = importlib.util.spec_from_file_location("make_install_links", _SCRIPT)
links = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(links)


def test_vscode_deeplink_decodes_to_server_json():
    link = links.vscode_deeplink()
    assert link.startswith("vscode:mcp/install?")
    payload = json.loads(unquote(link.split("?", 1)[1]))
    assert payload == {"name": "aec-model-bridge", **links.SERVER}
    assert payload["command"] == "uvx"
    assert payload["env"] == {"MCP_REVIT_MODE": "bridge"}
    assert "aec-model-bridge" == payload["args"][-1]


def test_vscode_redirect_decodes_to_server_json():
    parts = urlsplit(links.vscode_redirect())
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "vscode.dev", "/redirect/mcp/install")
    query = parse_qs(parts.query)
    assert query["name"] == ["aec-model-bridge"]
    assert json.loads(query["config"][0]) == links.SERVER


def test_vscode_cli_json_roundtrips():
    cli = links.vscode_cli()
    prefix = 'code --add-mcp "'
    assert cli.startswith(prefix) and cli.endswith('"')
    payload = json.loads(cli[len(prefix) : -1].replace('\\"', '"'))
    assert payload == {"name": "aec-model-bridge", **links.SERVER}


def test_cursor_links_decode_to_server_json():
    for link in (links.cursor_deeplink(), links.cursor_web_link()):
        query = parse_qs(urlsplit(link).query)
        assert query["name"] == ["aec-model-bridge"]
        assert json.loads(base64.b64decode(query["config"][0])) == links.SERVER
    assert links.cursor_deeplink().startswith("cursor://anysphere.cursor-deeplink/mcp/install?name=")


def test_server_needs_no_directory_config():
    assert set(links.SERVER["env"]) == {"MCP_REVIT_MODE"}


def test_readme_uses_current_links():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for key in ("cursor_web_link", "claude_desktop_bundle"):
        assert links.all_links()[key] in readme, key
    assert "docs/install-buttons.md#vs-code" in readme
