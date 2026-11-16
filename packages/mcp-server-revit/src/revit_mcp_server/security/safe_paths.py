"""One place that turns a caller-supplied id into a file path inside a known folder.

Plan ids, recipe ids, proof ids and snapshot ids all arrive from outside (a tool
argument, a panel request, the command line) and end up in a file name. Every such
path is built here, in three steps:

  1. the id must match a strict allow-list pattern in full (no separators, dots,
     NUL, drive letters, UNC, whitespace or look-alike Unicode can pass);
  2. the file is placed under a known root with ``os.path.join``;
  3. the result is resolved with ``os.path.realpath`` and must still sit directly
     inside that root, so a symlink or junction at the file cannot lead out of it.

This is the sanitiser shape CodeQL's ``py/path-injection`` query recognises (normalise,
then ``startswith`` the root plus a separator), and it is genuinely sufficient: step 1
alone already rules out traversal, steps 2 and 3 catch links.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Optional, Pattern

# The shape create_plan makes. Also used by security/approval.py.
PLAN_ID_RE = re.compile(r"plan_[0-9a-f]{12}")
# Snapshot ids are 26-character ULIDs (mock and semantic engine) or 32 hex digits (Revit add-in).
# The wider class also accepts the short names the tests and older workspaces use; it still has
# no dot, separator or colon, so it can never name another folder.
SNAPSHOT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Called with "name" (the id failed the allow-list) or "outside" (the resolved file left the folder).
Refuse = Callable[[str], Exception]


def safe_child(
    root: Any,
    name: Any,
    suffix: str,
    allowed: Pattern[str],
    refuse: Refuse,
    subdir: Optional[str] = None,
) -> Path:
    """``<root>[/<subdir>]/<name><suffix>``, or raise ``refuse(reason)``.

    ``name`` must match ``allowed`` in full. ``suffix`` and ``subdir`` are the caller's own
    constants. The resolved file must be a direct child of the folder (``subdir`` is not
    followed when it is a link). The folder need not exist yet.
    """
    if not isinstance(name, str) or not allowed.fullmatch(name):
        raise refuse("name")
    base = os.path.realpath(os.fspath(root))
    folder = os.path.join(base, subdir) if subdir else base
    candidate = os.path.normpath(os.path.realpath(os.path.join(folder, name + suffix)))
    if not candidate.startswith(os.path.join(base, "")):
        raise refuse("outside")
    if os.path.normcase(os.path.dirname(candidate)) != os.path.normcase(folder):
        raise refuse("outside")
    return Path(candidate)


def snapshot_file(snapshots_dir: Any, snapshot_id: Any) -> Path:
    """``<snapshots_dir>/<snapshot_id>.json`` for a plain snapshot id; ValueError otherwise."""
    def refuse(_reason: str) -> Exception:
        return ValueError("snapshot_id must be a plain snapshot name inside the workspace snapshots folder.")

    return safe_child(snapshots_dir, snapshot_id, ".json", SNAPSHOT_ID_RE, refuse)
