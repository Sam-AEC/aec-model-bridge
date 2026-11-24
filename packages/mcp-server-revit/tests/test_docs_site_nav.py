"""Every page in docs/ is either in the mkdocs nav or excluded.

The docs workflow builds with ``mkdocs build --strict``, which fails on pages
missing from the nav. This test finds that locally, without mkdocs installed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"


def _nav_pages(node) -> set[str]:
    pages: set[str] = set()
    if isinstance(node, str):
        if node.endswith(".md"):
            pages.add(node)
    elif isinstance(node, list):
        for item in node:
            pages |= _nav_pages(item)
    elif isinstance(node, dict):
        for value in node.values():
            pages |= _nav_pages(value)
    return pages


def _config() -> dict:
    text = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    # mkdocs.yml may hold !!python tags; this test only needs plain keys.
    return yaml.load(text, Loader=yaml.BaseLoader)


def test_every_doc_page_is_in_nav_or_excluded():
    config = _config()
    excluded = [line.strip() for line in config.get("exclude_docs", "").splitlines() if line.strip()]
    nav = _nav_pages(config["nav"])
    missing = []
    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS).as_posix()
        if any(rel == ex or rel.startswith(ex.rstrip("/") + "/") for ex in excluded):
            continue
        if rel not in nav:
            missing.append(rel)
    assert not missing, f"Add these pages to the nav in mkdocs.yml: {missing}"


def test_every_nav_page_exists():
    nav = _nav_pages(_config()["nav"])
    absent = sorted(page for page in nav if not (DOCS / page).is_file())
    assert not absent, f"mkdocs.yml nav names missing pages: {absent}"
