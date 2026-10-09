#!/usr/bin/env python3
"""Build the README hero image: AEC Model Bridge in the centre, the AI clients,
BIM apps and protocol/runtime tools it connects orbiting around it.

Writes docs/images/ecosystem-orbit.svg and ecosystem-orbit.png.

Logos come from Simple Icons (pinned release, CC0 icon data). The marks are
trademarks of their owners and are shown only to identify what the project works
with, in one neutral colour, with no implied endorsement (see TRADEMARKS.md).
Tools without a Simple Icons mark, or whose owners had their icon removed from
the set (OpenAI, VS Code, Power BI), are drawn as plain text tiles on purpose
instead of imitating or hunting down their logo.

  python scripts/make_ecosystem_image.py
  python scripts/make_ecosystem_image.py --browser "C:/Path/to/msedge.exe"
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
ICONS_VERSION = "16.34.0"
ICON_URL = "https://cdn.jsdelivr.net/npm/simple-icons@%s/icons/%s.svg"
W, H = 1600, 900
CX, CY = 800, 440
FONT = "'Segoe UI','Inter','Helvetica Neue',Arial,sans-serif"

TEAL, INDIGO, SLATE, AMBER = "#2DD4BF", "#818CF8", "#94A3B8", "#F59E0B"

# (label, simple-icons slug or None, in_progress, text-only tile)
RINGS = [
    dict(name="AI clients", color=TEAL, rx=290, ry=135, start=-90 - 36, items=[
        ("Claude", "claude", False), ("Codex", None, False), ("Copilot", "githubcopilot", False),
        ("Cursor", "cursor", False), ("VS Code", None, False)]),
    dict(name="BIM and design apps", color=INDIGO, rx=500, ry=215, start=-90 - 30, items=[
        ("Revit", "autodesk", False), ("Rhino", "rhinoceros", False), ("IFC", None, False),
        ("Speckle", None, False), ("Navisworks", "autodesk", True), ("Power BI", None, True)]),
    dict(name="Protocol and runtime", color=SLATE, rx=700, ry=290, start=-90 - 45, items=[
        ("MCP", "modelcontextprotocol", False), ("Python", "python", False),
        ("Docker", "docker", False), ("GitHub", "github", False)]),
]
TILE = 92


def icon_paths(slug: str) -> str:
    with urllib.request.urlopen(ICON_URL % (ICONS_VERSION, slug), timeout=30) as r:
        svg = r.read().decode("utf-8")
    paths = re.findall(r'<path[^>]*\sd="([^"]+)"', svg)
    if not paths:
        sys.exit(f"No path data in icon {slug}")
    return " ".join(paths)


def pier_mark() -> str:
    """Inner SVG markup of the project mark (assets/logo-mark.svg), minus the root tag."""
    svg = (ROOT / "assets" / "logo-mark.svg").read_text(encoding="utf-8")
    return re.sub(r"</?svg[^>]*>", "", svg).strip()


def tile(x: float, y: float, scale: float, opacity: float, label: str, path: str | None, dashed: bool, color: str) -> str:
    s = TILE
    stroke = AMBER if dashed else "rgba(255,255,255,0.28)"
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    g = [f'<g transform="translate({x:.1f} {y:.1f}) scale({scale:.3f})" opacity="{opacity:.2f}">']
    # opaque base first, so orbit lines never show through the glass tile
    g.append(f'<rect x="{-s/2}" y="{-s/2}" width="{s}" height="{s}" rx="22" fill="#111C33"/>')
    g.append(f'<rect x="{-s/2}" y="{-s/2}" width="{s}" height="{s}" rx="22" fill="url(#tile)" '
             f'stroke="{stroke}" stroke-width="1.6"{dash} filter="url(#lift)"/>')
    g.append(f'<rect x="{-s/2}" y="{-s/2}" width="{s}" height="3" rx="1.5" fill="{color}" opacity="0.75" '
             f'transform="translate(0 0)" clip-path="url(#tileTop)"/>')
    if path:
        k = 38 / 24
        g.append(f'<g transform="translate({-19} {-33}) scale({k:.3f})"><path d="{path}" fill="#F8FAFC" fill-opacity="0.94"/></g>')
        g.append(f'<text x="0" y="31" text-anchor="middle" font-family="{FONT}" font-size="13.5" '
                 f'font-weight="600" fill="#CBD5E1">{label}</text>')
    else:
        size = 26 if len(label) <= 3 else 17
        g.append(f'<text x="0" y="{size*0.35:.1f}" text-anchor="middle" font-family="{FONT}" font-size="{size}" '
                 f'font-weight="700" fill="#F8FAFC" letter-spacing="0.5">{label}</text>')
    if dashed:
        g.append(f'<text x="0" y="{s/2+18}" text-anchor="middle" font-family="{FONT}" font-size="11.5" '
                 f'font-weight="600" fill="{AMBER}">in progress</text>')
    g.append("</g>")
    return "".join(g)


def build() -> str:
    paths = {slug: icon_paths(slug) for r in RINGS for _l, slug, _d in r["items"] if slug}
    back, front, ring_back, ring_front = [], [], [], []
    for r in RINGS:
        rx, ry, c = r["rx"], r["ry"], r["color"]
        # back half (top, y < CY) is dimmer and sits behind the hub; front half is crisper
        ring_back.append(f'<path d="M {CX-rx} {CY} A {rx} {ry} 0 0 1 {CX+rx} {CY}" fill="none" stroke="{c}" '
                         f'stroke-opacity="0.22" stroke-width="1.4" stroke-dasharray="2 6" stroke-linecap="round"/>')
        ring_front.append(f'<path d="M {CX+rx} {CY} A {rx} {ry} 0 0 1 {CX-rx} {CY}" fill="none" stroke="{c}" '
                          f'stroke-opacity="0.55" stroke-width="1.6"/>')
        n = len(r["items"])
        for i, (label, slug, dashed) in enumerate(r["items"]):
            th = math.radians(r["start"] + i * 360 / n)
            x, y = CX + rx * math.cos(th), CY + ry * math.sin(th)
            d = (math.sin(th) + 1) / 2          # 0 = far side, 1 = near side
            html = tile(x, y, 0.80 + 0.22 * d, 0.55 + 0.45 * d, label, paths.get(slug) if slug else None, dashed, c)
            (front if y >= CY else back).append(html)

    hub = f'''
  <circle cx="{CX}" cy="{CY}" r="210" fill="url(#hubGlow)"/>
  <circle cx="{CX}" cy="{CY}" r="128" fill="none" stroke="{TEAL}" stroke-opacity="0.28" stroke-width="1.5"/>
  <circle cx="{CX}" cy="{CY}" r="104" fill="none" stroke="{TEAL}" stroke-opacity="0.16" stroke-width="1.5"/>
  <g transform="translate({CX-80} {CY-80}) scale({160/96:.4f})" filter="url(#lift)">{pier_mark()}</g>'''

    legend_items = [(TEAL, RINGS[0]["name"]), (INDIGO, RINGS[1]["name"]), (SLATE, RINGS[2]["name"])]
    legend, lx = [], 56
    for color, name in legend_items:
        legend.append(f'<circle cx="{lx}" cy="{H-44}" r="5" fill="{color}"/>'
                      f'<text x="{lx+14}" y="{H-39}" font-family="{FONT}" font-size="15" fill="#94A3B8">{name}</text>')
        lx += 36 + len(name) * 8.6
    legend.append(f'<rect x="{lx}" y="{H-49}" width="20" height="10" rx="3" fill="none" stroke="{AMBER}" stroke-dasharray="3 2.5"/>'
                  f'<text x="{lx+28}" y="{H-39}" font-family="{FONT}" font-size="15" fill="#94A3B8">in progress</text>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img"
 aria-label="AEC Model Bridge at the centre, connecting AI clients such as Claude, Codex, Copilot, Cursor and VS Code with BIM and design apps such as Revit, Rhino, IFC, Speckle, Navisworks and Power BI, over the Model Context Protocol">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0A1020"/><stop offset="1" stop-color="#0F1B33"/></linearGradient>
    <radialGradient id="hubGlow"><stop offset="0" stop-color="{TEAL}" stop-opacity="0.34"/><stop offset="0.55" stop-color="{TEAL}" stop-opacity="0.10"/><stop offset="1" stop-color="{TEAL}" stop-opacity="0"/></radialGradient>
    <radialGradient id="vignette" cx="0.5" cy="0.5" r="0.75"><stop offset="0.6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.45"/></radialGradient>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0.13"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0.04"/></linearGradient>
    <pattern id="dots" width="30" height="30" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1.1" fill="#FFFFFF" fill-opacity="0.07"/></pattern>
    <clipPath id="tileTop"><rect x="{-TILE/2}" y="{-TILE/2}" width="{TILE}" height="{TILE}" rx="22"/></clipPath>
    <filter id="lift" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000" flood-opacity="0.45"/></filter>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <rect width="{W}" height="{H}" fill="url(#dots)"/>
  {"".join(ring_back)}
  {"".join(back)}
  {hub}
  {"".join(ring_front)}
  {"".join(front)}
  <rect width="{W}" height="{H}" fill="url(#vignette)"/>
  <text x="56" y="76" font-family="{FONT}" font-size="36" font-weight="700" fill="#F8FAFC">AEC Model Bridge</text>
  <text x="56" y="108" font-family="{FONT}" font-size="18" fill="#94A3B8">One MCP server between your AI assistant and your BIM tools</text>
  {"".join(legend)}
  <text x="{W-56}" y="{H-39}" text-anchor="end" font-family="{FONT}" font-size="15" fill="#94A3B8">You approve every change before it reaches the model</text>
</svg>
'''


def find_browser(hint: str | None) -> str:
    cands = [hint] if hint else [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe", "msedge", "chrome", "google-chrome", "chromium"]
    for c in cands:
        found = shutil.which(c) or (c if Path(c).exists() else None)
        if found:
            return found
    sys.exit("No Edge or Chrome found. Pass --browser <path>.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--browser")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    svg = build()
    svg_path = OUT / "ecosystem-orbit.svg"
    svg_path.write_text(svg, encoding="utf-8")
    png_path = OUT / "ecosystem-orbit.png"
    page = Path(tempfile.mkdtemp(prefix="orbit-")) / "page.html"
    page.write_text(f'<!doctype html><meta charset="utf-8"><body style="margin:0;background:#0A1020">{svg}</body>', encoding="utf-8")
    browser = args.browser or find_browser(None)
    flags = ["--headless", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
             f"--user-data-dir={tempfile.mkdtemp(prefix='orbit-profile-')}", "--force-device-scale-factor=2",
             f"--window-size={W},{H}", "--virtual-time-budget=15000", f"--screenshot={png_path}", page.as_uri()]
    if sys.platform == "win32":
        # Edge and Chrome are GUI-subsystem programs on Windows; launch through PowerShell.
        quoted = ", ".join("'" + f.replace("'", "''") + "'" for f in flags)
        subprocess.run(["powershell", "-NoProfile", "-Command", f"& '{browser}' @({quoted}) 2>$null | Out-Null"],
                       capture_output=True, timeout=180)
    else:
        subprocess.run([browser, *flags], capture_output=True, timeout=180)
    if not png_path.exists():
        sys.exit("Browser did not produce the PNG.")
    print(f"{svg_path.relative_to(ROOT)}  {svg_path.stat().st_size // 1024} KB")
    print(f"{png_path.relative_to(ROOT)}  {png_path.stat().st_size // 1024} KB  ({W*2}x{H*2})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
