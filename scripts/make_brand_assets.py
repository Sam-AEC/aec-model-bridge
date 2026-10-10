"""Regenerate raster brand assets from the Pier mark geometry (see assets/logo-mark.svg).

Usage: python scripts/make_brand_assets.py      (needs Pillow)

Writes assets/icon.ico, assets/logo-mark-512.png and the Inno Setup wizard bitmaps in
assets/installer/. The geometry mirrors assets/logo-mark.svg and UI/BrandMark.cs.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
TILE = (0x11, 0x19, 0x23, 255)
TOP, LEFT, RIGHT = (0x1C, 0xB5, 0xCA, 255), (255, 255, 255, 255), (0xAE, 0xBC, 0xCB, 255)


def arch(m, k):
    a, b, c, d, e, f = m
    pts = [(0.24, 1.02), (0.24, 0.66)]
    for i in range(1, 32):
        t = math.pi * (1 - i / 32)
        pts.append((0.5 + 0.26 * math.cos(t), 0.66 - 0.26 * math.sin(t)))
    pts += [(0.76, 0.66), (0.76, 1.02)]
    return [((a * u + c * v + e) * k, (b * u + d * v + f) * k) for u, v in pts]


def mark(size, arches=True, rounded=True):
    """Render the 96-unit tile + mark at `size` px (8x supersampled)."""
    s = 8
    n = size * s
    k = n / 96
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    radius = (20 if arches else 14) * k if rounded else 0
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=radius, fill=TILE)
    p = lambda pts: [(x * k, y * k) for x, y in pts]
    top = [(48, 16), (76, 32), (48, 48), (20, 32)]
    left = [(20, 32), (48, 48), (48, 80), (20, 64)]
    right = [(48, 48), (76, 32), (76, 64), (48, 80)]
    for poly, col in ((top, TOP), (left, LEFT), (right, RIGHT)):
        d.polygon(p(poly), fill=col)
        d.line(p(poly + [poly[0]]), fill=TILE, width=max(1, int(2.5 * k)), joint="curve")
    if arches:
        d.polygon(arch((28, 16, 0, 32, 20, 32), k), fill=TILE)
        d.polygon(arch((28, -16, 0, 32, 48, 48), k), fill=TILE)
    return im.resize((size, size), Image.LANCZOS)


def main():
    raise SystemExit(
        "Retired: this script draws the old Pier mark. The current brand assets (Ember mesh) are "
        "vector artwork committed in assets/; see docs/design/brand.md. Edit the SVG masters and "
        "re-export instead of running this."
    )
    assets = ROOT / "assets"
    (assets / "installer").mkdir(parents=True, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [mark(sz, arches=sz > 20) for sz in sizes]
    frames[-1].save(assets / "icon.ico", sizes=[(sz, sz) for sz in sizes], append_images=frames[:-1])
    mark(512).save(assets / "logo-mark-512.png")

    # Inno Setup wizard images: 164x314 side panel, 55x58 corner icon.
    big = Image.new("RGB", (164, 314), TILE[:3])
    big.paste(mark(104), (30, 40), mark(104))
    ImageDraw.Draw(big).rectangle([0, 310, 163, 313], fill=(0x1C, 0xB5, 0xCA))
    big.save(assets / "installer" / "wizard-large.bmp")
    small = Image.new("RGB", (55, 58), (255, 255, 255))
    small.paste(mark(44), (6, 7), mark(44))
    small.save(assets / "installer" / "wizard-small.bmp")


if __name__ == "__main__":
    main()
