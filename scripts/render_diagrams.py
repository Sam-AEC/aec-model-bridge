#!/usr/bin/env python3
"""Render docs/diagrams/*.mmd to PNG images in docs/images/ (light and dark).

Directory sites that mirror the README do not run Mermaid, so the README shows
these images instead of code blocks. The .mmd files stay the source of truth.

Needs Microsoft Edge (or Chrome) and Python 3.9+. The Mermaid library is
downloaded once, pinned, into a temp folder.

  python scripts/render_diagrams.py
  python scripts/render_diagrams.py --browser "C:/Path/to/msedge.exe"
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "diagrams"
OUT = ROOT / "docs" / "images"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.0/dist/mermaid.min.js"
BACKGROUNDS = {"light": "#ffffff", "dark": "#0d1117"}
PAD = 24
PROFILE = tempfile.mkdtemp(prefix="render-diagrams-profile-")

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge", "chrome", "google-chrome", "chromium",
]

PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0;background:{bg}">
<div id="wrap" style="display:inline-block;padding:{pad}px"><div id="g"></div></div><pre id="dim" style="display:none"></pre>
<script src="mermaid.min.js"></script><script>
(async function () {{
  mermaid.initialize({{ startOnLoad: false }});
  var out = await mermaid.render('d', {src});
  document.getElementById('g').innerHTML = out.svg;
  var svg = document.querySelector('#g svg');
  var vb = svg.viewBox.baseVal;
  svg.removeAttribute('style');
  svg.setAttribute('width', vb.width);
  svg.setAttribute('height', vb.height);
  var r = document.getElementById('wrap').getBoundingClientRect();
  document.getElementById('dim').textContent = 'DIM ' + Math.ceil(r.width) + 'x' + Math.ceil(r.height);
}})();
</script></body>"""


def find_browser(hint: str | None) -> str:
    for cand in ([hint] if hint else BROWSERS):
        found = shutil.which(cand) or (cand if Path(cand).exists() else None)
        if found:
            return found
    sys.exit("No Edge or Chrome found. Pass --browser <path>.")


def run(browser: str, args: list[str]) -> str:
    """Run the browser and return what it printed to stdout.

    Edge and Chrome are GUI-subsystem programs on Windows and do not write to a
    pipe that Python captures directly, so go through PowerShell, which does.
    """
    full = [browser, "--headless", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            f"--user-data-dir={PROFILE}"] + args
    if sys.platform == "win32":
        quoted = ", ".join("'" + a.replace("'", "''") + "'" for a in full[1:])
        script = f"& '{full[0]}' @({quoted}) 2>$null | Out-String"
        done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                              capture_output=True, timeout=180)
    else:
        done = subprocess.run(full, capture_output=True, timeout=180)
    return done.stdout.decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--browser")
    args = parser.parse_args()
    browser = find_browser(args.browser)
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="diagrams-"))
    lib = work / "mermaid.min.js"
    urllib.request.urlretrieve(MERMAID_URL, lib)
    for mmd in sorted(SRC.glob("*.mmd")):
        source = mmd.read_text(encoding="utf-8")
        for mode, bg in BACKGROUNDS.items():
            page = work / f"{mmd.stem}-{mode}.html"
            page.write_text(PAGE.format(bg=bg, pad=PAD, src=json.dumps(source)), encoding="utf-8")
            url = page.as_uri()
            dom = run(browser, ["--virtual-time-budget=30000", "--dump-dom", url])
            m = re.search(r"DIM (\d+)x(\d+)", dom)
            if not m:
                sys.exit(f"Could not render {mmd.name} ({mode}); the Mermaid source may be invalid.")
            width, height = int(m.group(1)), int(m.group(2))
            target = OUT / f"{mmd.stem}-{mode}.png"
            run(browser, ["--virtual-time-budget=30000", "--force-device-scale-factor=2",
                          f"--window-size={width},{height}", f"--screenshot={target}", url])
            print(f"{target.relative_to(ROOT)}  {width}x{height} @2x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
