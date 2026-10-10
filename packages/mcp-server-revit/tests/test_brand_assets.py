"""Brand asset checks: referenced images exist, icon.ico has the expected sizes."""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
READMES = [ROOT / "README.md", *sorted((ROOT / "docs" / "i18n").glob("README.*.md"))]
ICO_SIZES = {16, 24, 32, 48, 64, 128, 256}
MAX_BYTES = 1_500_000


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _bmp_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:2] == b"BM"
    w, h = struct.unpack("<ii", data[18:26])
    return w, abs(h)


@pytest.mark.parametrize("readme", READMES, ids=lambda p: p.name)
def test_readme_images_exist(readme: Path) -> None:
    text = readme.read_text(encoding="utf-8")
    refs = re.findall(r'<img[^>]+src="([^"]+)"', text) + re.findall(
        r"!\[[^\]]*\]\(([^)\s]+)", text
    )
    local = [r for r in refs if not re.match(r"^[a-z]+://", r)]
    assert local, "README should reference at least the header mark"
    for ref in local:
        assert (readme.parent / ref).is_file(), f"{readme.name}: missing image {ref}"


@pytest.mark.parametrize("readme", READMES, ids=lambda p: p.name)
def test_readme_header_is_text_free_mark(readme: Path) -> None:
    text = readme.read_text(encoding="utf-8")
    m = re.search(r'<img src="([^"]*assets/logo-mark\.svg)" alt="([^"]*)"', text)
    assert m, f"{readme.name}: header image is not assets/logo-mark.svg"
    assert m.group(2) == "AEC Model Bridge logo"
    assert "<text" not in (readme.parent / m.group(1)).read_text(encoding="utf-8")


def test_mark_svgs_have_no_text() -> None:
    for svg in [
        ROOT / "assets" / "logo.svg",
        ROOT / "assets" / "logo-mark.svg",
        *(ROOT / "assets" / "brand").glob("*.svg"),
    ]:
        assert "<text" not in svg.read_text(encoding="utf-8"), svg.name


def test_icon_ico_sizes() -> None:
    data = (ROOT / "assets" / "icon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    sizes = set()
    for i in range(count):
        w, h = data[6 + 16 * i : 8 + 16 * i]
        sizes.add((w or 256, h or 256))
    assert sizes == {(s, s) for s in ICO_SIZES}


def test_raster_sizes() -> None:
    assert _png_size(ROOT / "assets" / "logo-mark-512.png") == (512, 512)
    assert _png_size(ROOT / "assets" / "social-preview.png") == (1280, 640)
    assert _png_size(ROOT / "extensions" / "vscode" / "media" / "icon.png") == (
        256,
        256,
    )
    assert _bmp_size(ROOT / "assets" / "installer" / "wizard-large.bmp") == (164, 314)
    assert _bmp_size(ROOT / "assets" / "installer" / "wizard-small.bmp") == (55, 58)


def test_asset_files_are_small() -> None:
    for folder in (ROOT / "assets", ROOT / "extensions" / "vscode" / "media"):
        for f in folder.rglob("*"):
            if f.is_file():
                assert f.stat().st_size <= MAX_BYTES, f
