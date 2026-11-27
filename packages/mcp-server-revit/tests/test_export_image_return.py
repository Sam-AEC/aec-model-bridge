"""revit_export_image return_image: the exported PNG as an MCP image block (issue #211).

The add-in result is faked; a small PNG is written to a tmp workspace. No Revit.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import struct
import zlib
from types import SimpleNamespace

import pytest
from mcp.types import ImageContent, TextContent

from revit_mcp_server import image_content, mcp_server
from revit_mcp_server.security.workspace import WorkspaceMonitor

TOOL = "revit_export_image"


def png_bytes(size: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Gate:
    approval_mode = "ask_first"

    def claim_action(self, name, arguments):
        return None

    def finish_action(self, claim, ok, error=None):
        pass

    def audit_dev_call(self, name, arguments, mutating):
        pass


class Provider:
    def __init__(self, result):
        self.result = result

    async def execute_tool(self, name, arguments):
        return self.result


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    provider = Provider({})
    monkeypatch.setattr(mcp_server, "registry", SimpleNamespace(
        lookup_tool_provider=lambda name: provider, lookup_tool=lambda name: SimpleNamespace(is_mutating=False)))
    monkeypatch.setattr(mcp_server, "approval_provider", SimpleNamespace(gate=Gate()))
    monkeypatch.setattr(mcp_server, "workspace_monitor", WorkspaceMonitor([root]))
    return SimpleNamespace(root=root, provider=provider)


def export(ws, path, **extra):
    ws.provider.result = {
        "view_id": 1, "file_path": str(path), "file_exists": True, "status": "success",
        "file_size_bytes": path.stat().st_size if path.exists() else 0, **extra,
    }
    return ws.provider.result


def call(ws, **arguments):
    args = {"view_id": 1, "output_path": str(ws.root / "v.png"), **arguments}
    return asyncio.run(mcp_server.call_tool(TOOL, args))


def blocks(result, kind):
    return [c for c in result if isinstance(c, kind)]


def test_option_on_returns_one_image_block_next_to_the_json_text(ws):
    path = ws.root / "v.png"
    path.write_bytes(png_bytes())
    export(ws, path)
    result = call(ws, return_image=True)
    images = blocks(result, ImageContent)
    assert len(images) == 1
    assert images[0].mimeType == "image/png"
    assert base64.b64decode(images[0].data) == path.read_bytes()
    texts = blocks(result, TextContent)
    assert texts[0].text.startswith("✓ revit_export_image executed successfully")
    body = json.loads(texts[0].text.split("Result:\n", 1)[1])
    assert body["status"] == "success" and body["file_size_bytes"] == path.stat().st_size


def test_option_off_is_unchanged(ws):
    path = ws.root / "v.png"
    path.write_bytes(png_bytes())
    export(ws, path)
    plain = call(ws)
    explicit = call(ws, return_image=False)
    assert len(plain) == 1 and isinstance(plain[0], TextContent)
    assert [c.model_dump() for c in plain] == [c.model_dump() for c in explicit]


def test_over_the_cap_is_refused_naming_the_cap_and_keeps_the_json(ws, monkeypatch):
    monkeypatch.setattr(image_content, "MAX_IMAGE_BYTES", 100)
    path = ws.root / "v.png"
    path.write_bytes(png_bytes(40))
    assert path.stat().st_size > 100
    export(ws, path)
    result = call(ws, return_image=True)
    assert blocks(result, ImageContent) == []
    texts = blocks(result, TextContent)
    assert any("100 bytes" in t.text and "not returned" in t.text for t in texts)
    assert '"status": "success"' in texts[0].text  # the JSON result is still there


def test_cap_is_two_mebibytes():
    assert image_content.MAX_IMAGE_BYTES == 2 * 1024 * 1024


def test_file_exists_false_gives_a_plain_message(ws):
    ws.provider.result = {"view_id": 1, "file_path": None, "file_exists": False, "status": "success"}
    result = call(ws, return_image=True)
    assert blocks(result, ImageContent) == []
    assert "no image file" in blocks(result, TextContent)[1].text.lower()


def test_addin_error_for_a_missing_file_is_the_plain_error_and_no_crash(ws):
    ws.provider.result = {"view_id": 1, "file_path": None, "file_exists": False, "status": "error",
                          "error": "Revit did not produce a new or updated image file."}
    result = call(ws, return_image=True)
    assert result.isError
    assert "did not produce" in result.content[0].text
    assert not [c for c in result.content if isinstance(c, ImageContent)]


def test_reported_file_that_is_gone_gives_a_plain_message(ws):
    export(ws, ws.root / "gone.png")
    ws.provider.result["file_exists"] = True
    result = call(ws, return_image=True)
    assert blocks(result, ImageContent) == []
    assert len(blocks(result, TextContent)) == 2


def test_path_outside_the_workspace_is_never_read(ws, tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(png_bytes())
    export(ws, outside)
    result = call(ws, return_image=True)
    assert blocks(result, ImageContent) == []
    assert "workspace" in blocks(result, TextContent)[1].text


def test_file_that_is_not_a_png_is_not_returned(ws):
    path = ws.root / "v.png"
    path.write_bytes(b"not an image")
    export(ws, path)
    result = call(ws, return_image=True)
    assert blocks(result, ImageContent) == []
    assert "PNG" in blocks(result, TextContent)[1].text


def test_non_png_export_is_not_returned(ws):
    path = ws.root / "v.jpg"
    path.write_bytes(png_bytes())
    export(ws, path)
    result = call(ws, return_image=True)
    assert blocks(result, ImageContent) == []
    assert "PNG" in blocks(result, TextContent)[1].text


def test_view_name_suffix_file_reported_by_the_addin_is_returned(ws):
    path = ws.root / "v - Level 1.png"
    path.write_bytes(png_bytes())
    export(ws, path)
    assert len(blocks(call(ws, return_image=True), ImageContent)) == 1


def test_schema_documents_the_option_and_the_cap():
    from revit_mcp_server.providers import revit as providers_revit
    src = open(providers_revit.__file__, encoding="utf-8").read()
    match = re.search(r'name="revit_export_image".*?"required"', src, re.S)
    assert match and "return_image" in match.group(0)
    assert "2 MB" in match.group(0)
