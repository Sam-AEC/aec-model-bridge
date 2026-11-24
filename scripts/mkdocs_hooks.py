"""MkDocs hook: point links that leave docs/ at the file on GitHub.

The docs link to repository files outside docs/ (CHANGELOG.md, .github/SECURITY.md,
package READMEs). Those links work on GitHub but are not part of the site, so
`mkdocs build --strict` reports them. This hook rewrites each one to the same file
on the main branch before MkDocs validates links. Links inside docs/ are left
alone, so a broken internal link still fails the strict build.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO_URL = "https://github.com/Sam-AEC/aec-model-bridge"
BRANCH = "main"

# Inline links and images: [text](target) or ![alt](target "title").
_INLINE = re.compile(r"(\]\()(<?)([^)\s>]+)(>?)((?:\s+\"[^\"]*\")?\))")
# Reference definitions: [label]: target
_REFDEF = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s+)(\S+)", re.MULTILINE)
_FENCE = re.compile(r"^(```|~~~)", re.MULTILINE)


def _rewrite(target: str, page_dir: str, docs_dir: Path, repo_root: Path) -> str:
    if not target or target.startswith(("#", "/", "mailto:")) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return target
    path, sep, anchor = target.partition("#")
    if not path:
        return target
    joined = posixpath.normpath(posixpath.join("docs", page_dir, path))
    if joined == "docs" or joined.startswith("docs/"):
        return target
    if joined.startswith(".."):
        return target
    full = repo_root / joined
    if not full.exists():
        return target
    kind = "tree" if full.is_dir() else "blob"
    return f"{REPO_URL}/{kind}/{BRANCH}/{joined}{sep}{anchor}"


def on_page_markdown(markdown: str, page, config, files) -> str:  # noqa: ARG001
    docs_dir = Path(config["docs_dir"]).resolve()
    repo_root = docs_dir.parent
    page_dir = posixpath.dirname(page.file.src_uri)

    def inline(match: re.Match[str]) -> str:
        new = _rewrite(match.group(3), page_dir, docs_dir, repo_root)
        return f"{match.group(1)}{match.group(2)}{new}{match.group(4)}{match.group(5)}"

    def refdef(match: re.Match[str]) -> str:
        return match.group(1) + _rewrite(match.group(2), page_dir, docs_dir, repo_root)

    # Leave fenced code blocks untouched: split on fence lines, rewrite even chunks.
    parts = re.split(r"(^(?:```|~~~).*$)", markdown, flags=re.MULTILINE)
    out: list[str] = []
    in_code = False
    for part in parts:
        if _FENCE.match(part):
            in_code = not in_code
            out.append(part)
        elif in_code:
            out.append(part)
        else:
            out.append(_REFDEF.sub(refdef, _INLINE.sub(inline, part)))
    return "".join(out)
