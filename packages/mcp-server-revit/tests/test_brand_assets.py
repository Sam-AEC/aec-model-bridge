"""Brand asset checks: the product keeps the Pier mark; Cerberus artwork stays in assets/cerberus."""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
READMES = [ROOT / "README.md", *sorted((ROOT / "docs" / "i18n").glob("README.*.md"))]
CERBERUS = ROOT / "assets" / "cerberus"
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


def _ico_sizes(path: Path) -> set[tuple[int, int]]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    return {(data[6 + 16 * i] or 256, data[7 + 16 * i] or 256) for i in range(count)}


@pytest.mark.parametrize("readme", READMES, ids=lambda p: p.name)
def test_readme_images_exist(readme: Path) -> None:
    text = readme.read_text(encoding="utf-8")
    refs = re.findall(r'<img[^>]+src="([^"]+)"', text) + re.findall(
        r"!\[[^\]]*\]\(([^)\s]+)", text
    )
    local = [r for r in refs if not re.match(r"^[a-z]+://", r)]
    assert local, "README should reference at least the header logo"
    for ref in local:
        assert (readme.parent / ref).is_file(), f"{readme.name}: missing image {ref}"


@pytest.mark.parametrize("readme", READMES, ids=lambda p: p.name)
def test_readme_header_is_the_product_logo(readme: Path) -> None:
    text = readme.read_text(encoding="utf-8")
    m = re.search(r'<img src="([^"]+)"', text)
    assert m, f"{readme.name}: no header image"
    assert m.group(1).endswith("assets/logo.svg"), (
        f"{readme.name}: header is not the product logo"
    )
    assert "cerberus" not in text.split("</div>")[0].lower()


def test_product_icon_and_rasters() -> None:
    assert _ico_sizes(ROOT / "assets" / "icon.ico") == {(s, s) for s in ICO_SIZES}
    assert _png_size(ROOT / "assets" / "logo-mark-512.png") == (512, 512)
    assert _png_size(ROOT / "extensions" / "vscode" / "media" / "icon.png") == (
        512,
        512,
    )
    assert _bmp_size(ROOT / "assets" / "installer" / "wizard-large.bmp") == (164, 314)
    assert _bmp_size(ROOT / "assets" / "installer" / "wizard-small.bmp") == (55, 58)


def test_product_mark_is_not_the_cerberus_mark() -> None:
    product = (ROOT / "assets" / "logo-mark.svg").read_text(encoding="utf-8")
    assert product != (CERBERUS / "mark.svg").read_text(encoding="utf-8")
    assert not (ROOT / "assets" / "social-preview.png").exists()


CERBERUS_FILES = [
    "mark.svg",
    "mark-16.svg",
    "mark-32.svg",
    "mark-dark-disc.svg",
    "mark-mono.svg",
    "mark-mono-badge.svg",
    "mark-512.png",
    "mark-1024.png",
    "cerberus.ico",
    "cerberus-hero.png",
]


@pytest.mark.parametrize("name", CERBERUS_FILES)
def test_cerberus_files_exist_and_are_small(name: str) -> None:
    f = CERBERUS / name
    assert f.is_file(), name
    assert f.stat().st_size <= MAX_BYTES, name


def test_cerberus_svgs_have_no_text() -> None:
    svgs = list(CERBERUS.glob("*.svg"))
    assert len(svgs) == 6
    for svg in svgs:
        assert "<text" not in svg.read_text(encoding="utf-8"), svg.name


def test_cerberus_rasters_and_icon() -> None:
    assert _ico_sizes(CERBERUS / "cerberus.ico") == {(s, s) for s in ICO_SIZES}
    assert _png_size(CERBERUS / "mark-512.png") == (512, 512)
    assert _png_size(CERBERUS / "mark-1024.png") == (1024, 1024)
    assert _png_size(CERBERUS / "cerberus-hero.png") == (1280, 640)
