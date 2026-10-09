#!/usr/bin/env python3
"""Build docs/images/readme/demo.gif: the approve loop, with the real panel UI.

    python3 docs/design/readme-visuals/demo/build_demo.py [--chromium PATH]

Needs Pillow and a Chromium or Chrome binary. The left pane (chat.html) and the
bottom strip (steps.html) are drawn here. The right pane is the real
panel/index.html and panel/app.js, fed example messages through a stub of the
WebView2 host, so what you see is the shipped panel with example data. The
values are illustrative and the session is simulated; the GIF says so.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = ROOT / "docs" / "images" / "readme" / "demo.gif"
PANEL = ROOT / "panel"

LEFT_W, PANE_H, RIGHT_W, STRIP_H = 760, 584, 520, 56
W, H = LEFT_W + RIGHT_W, PANE_H + STRIP_H

# frame -> (milliseconds on screen, step highlighted in the strip)
FRAMES = {1: (1700, 1), 2: (2300, 2), 3: (2500, 3), 4: (1000, 3), 5: (1900, 4), 6: (3800, 4)}

STUB = """<script>
window.chrome = { webview: { postMessage: function () {}, addEventListener: function (t, fn) { window.__h = fn; } } };
</script>"""

DRIVER = """<script>
(function () {
  var f = parseInt((location.hash || '#f1').slice(2), 10);
  function send(d) { window.__h({ data: d }); }
  send({ type: 'host.status', serverRunning: true, revitVersion: '2026', port: 3000, activeDocument: 'Example tower.rvt', isDarkTheme: false });
  send({ type: 'providers.updated', providers: { claude: true, codex: true } });
  send({ type: 'panel.view', view: 'plans' });
  var state = f >= 5 ? 'approved' : (f >= 3 ? 'pending' : null);
  var plans = state ? [{ plan_id: 'plan_7f3a', state: state, actions: [{ tool: 'revit_batch_set_parameters' }] }] : [];
  send({ type: 'plans.updated', result: { plans: plans } });
  if (f === 4) { document.querySelector('[data-decision="approve"]').style.filter = 'brightness(0.8)'; }
})();
</script>"""


def find_chromium(explicit):
    if explicit:
        return explicit
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in pathlib.Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
        return str(candidate)
    sys.exit("No Chromium found. Pass --chromium PATH.")


def shoot(chromium, url, width, height, out):
    cmd = [chromium, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           "--allow-file-access-from-files", f"--window-size={width},{height + 400}",
           "--virtual-time-budget=9000", f"--screenshot={out}", url]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return Image.open(out).convert("RGB").crop((0, 0, width, height))


def cursor(draw, x, y):
    pts = [(x, y), (x, y + 24), (x + 6, y + 18), (x + 11, y + 29), (x + 15, y + 27), (x + 10, y + 17), (x + 18, y + 17)]
    draw.polygon(pts, fill=(255, 255, 255), outline=(19, 32, 43))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chromium")
    args = parser.parse_args()
    chromium = find_chromium(args.chromium)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="amb-demo-"))
    html = (PANEL / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="./styles.css"', f'href="{(PANEL / "styles.css").as_uri()}"')
    html = html.replace('<script src="./app.js"></script>',
                        STUB + f'<script src="{(PANEL / "app.js").as_uri()}"></script>' + DRIVER)
    panel_page = tmp / "panel.html"
    panel_page.write_text(html, encoding="utf-8")

    frames, durations = [], []
    for n, (ms, step) in FRAMES.items():
        left = shoot(chromium, (HERE / "chat.html").as_uri() + f"#f{n}", LEFT_W, PANE_H, tmp / f"l{n}.png")
        right = shoot(chromium, panel_page.as_uri() + f"#f{n}", RIGHT_W, PANE_H, tmp / f"r{n}.png")
        strip = shoot(chromium, (HERE / "steps.html").as_uri() + f"#s{step}", W, STRIP_H, tmp / f"s{n}.png")
        canvas = Image.new("RGB", (W, H), (238, 242, 246))
        canvas.paste(left, (0, 0))
        canvas.paste(right, (LEFT_W, 0))
        canvas.paste(strip, (0, PANE_H))
        if n == 4:  # pointer over the Approve button
            draw = ImageDraw.Draw(canvas)
            cursor(draw, LEFT_W + 128, 200)
        frames.append(canvas)
        durations.append(ms)

    palettes = [f.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    palettes[0].save(OUT, save_all=True, append_images=palettes[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(frames)} frames)")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
