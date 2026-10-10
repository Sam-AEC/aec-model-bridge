"""Browser tests for the panel chat UI (panel/chat.js) in headless Chromium.

No npm dependencies: the page runs its own small in-page test runner
(tests/panel_web/lib.js) and Chromium's `--dump-dom` prints the JSON results, which
this module turns into one pytest case per browser case. Two pages are exercised:

* the REAL panel/index.html + app.js + chat.js with a stubbed `window.chrome.webview`
  (copied to a temp dir with only the stub and driver scripts injected, so the page's
  Content-Security-Policy is the real one and any inline script/style would be blocked);
* a standalone XSS / control-character page for the markdown renderer.

Skipped cleanly when no Chromium is available (set AMB_CHROMIUM to point at one).
Anything needing live WebView2 (clipboard permission, CSP on file://, IME, DPI) is NOT
covered here; see docs/dev-test-plan.md section E.
"""

from __future__ import annotations

import glob
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PANEL = ROOT / "panel"
WEB = Path(__file__).resolve().parent / "panel_web"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
)


def _chromium() -> str | None:
    env = os.environ.get("AMB_CHROMIUM")
    if env and Path(env).exists():
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    bases = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "/opt/pw-browsers", str(Path.home() / ".cache/ms-playwright")]
    for base in filter(None, bases):
        for pattern in ("chromium-*/chrome-linux/chrome", "chromium_headless_shell-*/chrome-linux/headless_shell"):
            hits = sorted(glob.glob(os.path.join(base, pattern)))
            if hits:
                return hits[-1]
    return None


def _run_page(tmp_path: Path, page: Path, width: int = 1000, height: int = 800) -> list[dict]:
    chrome = _chromium()
    if not chrome:
        pytest.skip("no Chromium available (set AMB_CHROMIUM)")
    profile = tmp_path / "profile"
    profile.mkdir(exist_ok=True)
    proc = subprocess.run(
        [
            chrome,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "--virtual-time-budget=60000",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    match = re.search(r'<pre id="amb-results">(.*?)</pre>', proc.stdout, re.S)
    assert match, f"no results in page output (exit {proc.returncode}): {proc.stderr[-400:]}"
    return json.loads(html.unescape(match.group(1)))


def _stage(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    shutil.copytree(PANEL, site / "panel")
    for name in ("lib.js", "stub.js", "app_driver.js", "xss_driver.js"):
        shutil.copy(WEB / name, site / name)
    return site


@pytest.fixture(scope="module")
def app_results(tmp_path_factory) -> list[dict]:
    tmp = tmp_path_factory.mktemp("panel_app")
    site = _stage(tmp)
    page = (site / "panel" / "index.html").read_text(encoding="utf-8")
    # Same page, same CSP; only the stub + runner scripts are added (same origin 'self').
    page = page.replace(
        '  <script src="./vendor/smd.min.js"></script>',
        '  <script src="../lib.js"></script>\n  <script src="../stub.js"></script>\n'
        '  <script src="./vendor/smd.min.js"></script>',
    )
    page = page.replace(
        '  <script src="./app.js"></script>',
        '  <script src="./app.js"></script>\n  <script src="../app_driver.js"></script>',
    )
    assert "../app_driver.js" in page and "../stub.js" in page
    (site / "panel" / "test_index.html").write_text(page, encoding="utf-8")
    return _run_page(tmp, site / "panel" / "test_index.html", width=1000, height=800)


@pytest.fixture(scope="module")
def xss_results(tmp_path_factory) -> list[dict]:
    tmp = tmp_path_factory.mktemp("panel_xss")
    site = _stage(tmp)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>chat xss</title>
<link rel="stylesheet" href="./panel/styles.css"><link rel="stylesheet" href="./panel/chat.css">
</head><body>
<script src="./lib.js"></script>
<script src="./panel/vendor/smd.min.js"></script>
<script src="./panel/vendor/highlight.core-min.js"></script>
<script src="./panel/chat.js"></script>
<script src="./xss_driver.js"></script>
</body></html>"""
    (site / "xss.html").write_text(page, encoding="utf-8")
    return _run_page(tmp, site / "xss.html")


def _names(driver: str) -> list[str]:
    src = (WEB / driver).read_text(encoding="utf-8")
    return re.findall(r'test\("((?:[^"\\]|\\.)*)"', src)


def _xss_names() -> list[str]:
    """Static names of the xss cases (the generated per-case names are listed from the data)."""
    src = (WEB / "xss_driver.js").read_text(encoding="utf-8")
    cases = re.findall(r'^\s+\["((?:[^"\\]|\\.)*)",', src, re.M)
    out = []
    for name in cases:
        out.append("xss: " + name)
        out.append("xss: " + name + " (streamed by character)")
    return out + [n for n in _names("xss_driver.js") if n != "xss: "]


def _check(results: list[dict], name: str) -> None:
    by_name = {r["name"]: r for r in results}
    assert name in by_name, f"case was not run in the browser: {name}"
    got = by_name[name]
    assert got["ok"], got.get("error")


APP_CASES = [n for n in _names("app_driver.js")]


@pytest.mark.parametrize("name", APP_CASES)
def test_panel_app_in_browser(app_results, name):
    _check(app_results, name)


XSS_CASES = _xss_names()


@pytest.mark.parametrize("name", XSS_CASES)
def test_chat_markdown_is_inert_in_browser(xss_results, name):
    _check(xss_results, name)


def test_every_browser_case_is_listed(app_results, xss_results):
    """Cases the pages ran must all be parametrised above, so none can fail unseen."""
    ran_app = {r["name"] for r in app_results}
    ran_xss = {r["name"] for r in xss_results}
    assert ran_app == set(APP_CASES)
    assert ran_xss == set(XSS_CASES)
