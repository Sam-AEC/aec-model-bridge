"""Static guards for the panel chat UI: CSP, no network from the panel, no HTML injection
of model text, vendored libraries match VENDOR.txt. Pure string/hash checks; they run
everywhere (no node, no browser)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[3] / "panel"
HTML = (PANEL / "index.html").read_text(encoding="utf-8")
APP_JS = (PANEL / "app.js").read_text(encoding="utf-8")
CHAT_JS = (PANEL / "chat.js").read_text(encoding="utf-8")
VENDOR = PANEL / "vendor"

def _code(text: str) -> str:
    """Source without block comments and whole-line // comments (prose may name the sinks)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


# Panel code we own (everything except the vendored libraries).
OWN_JS = sorted(p for p in PANEL.glob("*.js"))
OWN_CSS = sorted(p for p in PANEL.glob("*.css"))

REQUIRED_CSP = {
    "default-src": "'none'",
    "script-src": "'self'",
    "style-src": "'self'",
    "img-src": "'self' data:",
    "connect-src": "'none'",
    "object-src": "'none'",
    "base-uri": "'none'",
    "form-action": "'none'",
}


def _csp() -> dict[str, str]:
    m = re.search(
        r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"', HTML
    )
    assert m, "index.html has no Content-Security-Policy meta tag"
    out = {}
    for part in m.group(1).split(";"):
        part = part.strip()
        if part:
            name, _, value = part.partition(" ")
            out[name] = value.strip()
    return out


def test_csp_meta_is_present_and_strict():
    assert _csp() == REQUIRED_CSP


def test_csp_meta_precedes_every_script_and_stylesheet():
    meta = HTML.index("Content-Security-Policy")
    for tag in re.finditer(r"<(?:script|link)\b", HTML):
        assert tag.start() > meta, "a script/link is parsed before the CSP applies"


def test_page_has_no_inline_script_style_or_handlers():
    """The CSP (no 'unsafe-inline') would block these, so they must not exist."""
    for m in re.finditer(r"<script\b([^>]*)>", HTML):
        assert "src=" in m.group(1), "inline <script> would be blocked by the CSP"
    assert not re.search(r"<style\b", HTML), "inline <style> would be blocked"
    assert not re.search(r"\sstyle\s*=", HTML), "style attribute would be blocked"
    assert not re.search(r"\son[a-z]+\s*=", HTML, re.I), "inline event handler"
    assert 'href="#brand-mark"' in HTML  # same-document SVG refs are fine


def test_scripts_are_classic_local_files():
    """Classic scripts only: ES modules do not load over file://."""
    srcs = re.findall(r'<script\s+src="([^"]+)"', HTML)
    assert srcs == [
        "./vendor/smd.min.js",
        "./vendor/highlight.core-min.js",
        "./chat.js",
        "./app.js",
    ]
    assert "type=\"module\"" not in HTML
    for src in srcs:
        assert (PANEL / src).is_file()


@pytest.mark.parametrize("path", OWN_JS + sorted(VENDOR.glob("*.js")), ids=lambda p: p.name)
def test_panel_javascript_makes_no_network_calls(path):
    text = path.read_text(encoding="utf-8")
    forbidden = (
        r"\bfetch\s*\(",
        r"XMLHttpRequest",
        r"\bWebSocket\b",
        r"\bEventSource\b",
        r"sendBeacon",
        r"importScripts",
        r"\bimport\s*\(",
        r"serviceWorker",
        r"\bnew\s+Image\b",
        r"window\.open\s*\(",
        r"location\s*(?:\.href)?\s*=[^=]",
    )
    for pattern in forbidden:
        assert not re.search(pattern, text), f"{path.name}: {pattern}"


def test_panel_never_calls_the_hub_directly():
    # The C# host calls the hub; the panel only posts messages to it.
    for path in OWN_JS:
        text = path.read_text(encoding="utf-8")
        assert "127.0.0.1" not in text and "localhost" not in text, path.name
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", text), path.name


@pytest.mark.parametrize("path", OWN_CSS, ids=lambda p: p.name)
def test_panel_css_loads_nothing_external(path):
    text = path.read_text(encoding="utf-8")
    assert "@import" not in text
    assert not re.search(r"url\(\s*['\"]?(?!data:|#)", text), "css url() fetch"


def test_html_references_nothing_remote():
    refs = re.findall(r'(?:src|href)="([^"#][^"]*)"', HTML)
    for ref in refs:
        assert ref.startswith("./"), f"non-local reference {ref}"


# --------------------------------------------------- no HTML injection of model text

_HTML_SINKS = (
    r"\.innerHTML\b",
    r"\.outerHTML\b",
    r"insertAdjacentHTML",
    r"document\.write",
    r"createContextualFragment",
    r"srcdoc",
    r"\beval\s*\(",
    r"new\s+Function\b",
    r"setTimeout\s*\(\s*['\"`]",
)


def test_chat_renderer_has_no_html_sinks_at_all():
    code = _code(CHAT_JS)
    for pattern in _HTML_SINKS:
        assert not re.search(pattern, code), f"chat.js uses {pattern}"


def test_new_panel_files_have_no_html_sinks():
    """Any new panel script (not app.js, which predates this and escapes) must stay clean."""
    for path in OWN_JS:
        if path.name == "app.js":
            continue
        text = _code(path.read_text(encoding="utf-8"))
        for pattern in _HTML_SINKS:
            assert not re.search(pattern, text), f"{path.name} uses {pattern}"


def test_chat_text_goes_through_text_nodes():
    assert "body.textContent = visibleText(text, true)" in CHAT_JS
    assert "document.createTextNode(visibleText(t, true))" in CHAT_JS
    assert _code(CHAT_JS).count("DOMParser") == 1, "DOMParser is only for highlight.js output"


def test_app_js_html_sinks_do_not_touch_chat_or_model_text():
    """app.js templates were written with escapeHtml() (#99). Chat text and anything from
    `event.data` must never reach an innerHTML sink; a new sink needs a review."""
    sinks = re.findall(r"\.innerHTML\s*=", APP_JS)
    assert len(sinks) <= 11, "a new innerHTML assignment was added to app.js: review it"
    for name in ("chatRoot", "chat.", "chatMessage", "event.data"):
        for m in re.finditer(r"[^\n]*\.innerHTML[^\n]*", APP_JS):
            assert name not in m.group(0), f"innerHTML line mentions {name}"
    assert "chat.setProposals(state.plans)" in APP_JS


# ------------------------------------------------------------------- vendor integrity


def _vendor_hashes() -> dict[str, str]:
    text = (VENDOR / "VENDOR.txt").read_text(encoding="utf-8")
    out = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^(\S+\.js)\s", line)
        if m:
            current = m.group(1)
        h = re.search(r"sha256\s+([0-9a-f]{64})", line)
        if h and current:
            out[current] = h.group(1)
    return out


def test_vendored_libraries_match_vendor_txt():
    hashes = _vendor_hashes()
    assert set(hashes) == {"smd.min.js", "highlight.core-min.js"}
    for name, expected in hashes.items():
        actual = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} differs from VENDOR.txt"


def test_vendor_licences_are_shipped():
    assert "MIT License" in (VENDOR / "LICENSE.streaming-markdown.txt").read_text(encoding="utf-8")
    assert "BSD 3-Clause" in (VENDOR / "LICENSE.highlight.js.txt").read_text(encoding="utf-8")
    notes = (VENDOR / "VENDOR.txt").read_text(encoding="utf-8")
    assert "no CDN at runtime" in notes


def test_nothing_in_vendor_is_loaded_from_a_cdn():
    for path in PANEL.rglob("*"):
        if path.suffix in {".html", ".js", ".css"} and "vendor" not in path.parts:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"cdn\.|unpkg|jsdelivr|googleapis", text), path.name
