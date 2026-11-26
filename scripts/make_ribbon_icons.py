"""Render the ribbon icons of the AEC Bridge tab.

Each icon is a plain Microsoft Fluent regular glyph (MIT, see NOTICE) with no tile: light ink on the dark ribbon,
dark ink on the light one. The Panel icon is assets/logo-mark.svg.

    pip install resvg-py          # or cairosvg
    python scripts/make_ribbon_icons.py [--fluent path/to/fluent_lib.json]

Writes packages/revit-bridge-addin/Resources/RibbonIcons/<name>_<16|32>_<dark|light>.png. The add-in embeds
them (RevitBridge.csproj); IconGenerator picks the variant for Revit's theme. See docs/RIBBON_ICONS.md.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "packages", "revit-bridge-addin", "Resources", "RibbonIcons")
LOGO = os.path.join(ROOT, "assets", "logo-mark.svg")
FLUENT = os.path.join("C:\\", "wt", "cl-tools-design", "open-kit", "data", "fluent_lib.json")

SIZES = (16, 32)
INK = {"dark": "#D7DCE3", "light": "#2A313B"}

# file stem -> Fluent icon name; "panel" is the logo mark.
GLYPHS = {
    "approve": "clipboard_task",
    "healthcheck": "stethoscope",
    "connected": "plug_connected",
    "disconnected": "power",
    "reports": "document_text",
    "status": "pulse",
    "settings": "settings",
    "help": "question_circle",
    "about": "info",
}


def glyph_svg(glyph, ink):
    size, paths = glyph
    body = "".join(f'<path d="{d}" fill="{ink}"/>' for d in paths.split("|"))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">{body}</svg>'


def rasterizer():
    try:
        import resvg_py

        def render(svg, px):
            return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=px, height=px))

        return render
    except ImportError:
        pass
    try:
        import cairosvg

        def render(svg, px):
            return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=px, output_height=px)

        return render
    except ImportError:
        sys.exit("Install an SVG rasterizer first: pip install resvg-py (or cairosvg).")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fluent", default=FLUENT, help="path to fluent_lib.json from the icon kit")
    args = parser.parse_args()

    with open(args.fluent, encoding="utf-8") as fh:
        fluent = json.load(fh)
    with open(LOGO, encoding="utf-8") as fh:
        logo = fh.read()
    logo = re.sub(r'\s+role="img"\s+aria-label="[^"]*"', "", logo)
    render = rasterizer()

    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        if name.endswith(".png"):
            os.remove(os.path.join(OUT, name))

    for stem in ["panel"] + list(GLYPHS):
        for theme in INK:
            for px in SIZES:
                if stem == "panel":
                    svg = logo
                else:
                    svg = glyph_svg(fluent[GLYPHS[stem]]["r"], INK[theme])
                with open(os.path.join(OUT, f"{stem}_{px}_{theme}.png"), "wb") as fh:
                    fh.write(render(svg, px))
    print(f"wrote {(len(GLYPHS) + 1) * len(INK) * len(SIZES)} icons to {OUT}")


if __name__ == "__main__":
    main()
