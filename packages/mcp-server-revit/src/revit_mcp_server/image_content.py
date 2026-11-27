"""Return the PNG that ``revit_export_image`` wrote as an MCP image block (opt-in ``return_image``).

Read-only. Only the file the export reported (``file_path`` or ``file_paths``) is read, only inside the
workspace, and only if it is a PNG of at most ``MAX_IMAGE_BYTES``. Anything else gives a plain note;
the JSON result still names the file. An over-size image is refused, never truncated.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Optional, Tuple

from mcp.types import ImageContent

TOOL = "revit_export_image"
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def wants_image(name: str, arguments: Any) -> bool:
    return name == TOOL and isinstance(arguments, dict) and arguments.get("return_image") is True


def _reported_files(result: Any) -> list:
    data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
    if not isinstance(data, dict) or data.get("file_exists") is False:
        return []
    files = [data.get("file_path"), *(data.get("file_paths") or [])]
    return [f for f in files if isinstance(f, str) and f]


def image_block(result: Any, workspace: Any) -> Tuple[Optional[ImageContent], Optional[str]]:
    """One ``ImageContent`` for the exported PNG, or ``(None, plain note)``."""
    reported = _reported_files(result)
    if not reported:
        return None, "return_image: Revit reported no image file, so no image is returned."
    path = reported[0]
    if Path(path).suffix.lower() != ".png":
        return None, "return_image: only a PNG export can be returned; the exported file is not a PNG."
    try:
        resolved = workspace.assert_in_workspace(Path(path))
    except Exception:  # noqa: BLE001  fail closed on any workspace problem
        return None, "return_image: the exported file is outside the allowed workspace, so it is not read."
    try:
        if not resolved.is_file():
            return None, "return_image: the exported image file was not found, so no image is returned."
        with open(resolved, "rb") as handle:
            data = handle.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        return None, "return_image: the exported image file could not be read, so no image is returned."
    if len(data) > MAX_IMAGE_BYTES:
        return None, (
            f"return_image: the image is larger than the {MAX_IMAGE_BYTES} bytes (2 MB) cap and is not returned. "
            "The file stays in the workspace at the path in the result. Export a smaller width or height, or open the file."
        )
    if not data.startswith(PNG_SIGNATURE):
        return None, "return_image: the exported file is not a valid PNG, so no image is returned."
    return ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png"), None
