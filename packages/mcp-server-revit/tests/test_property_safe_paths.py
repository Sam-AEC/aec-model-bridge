"""Property tests of path safety (issue #296).

Generated hostile names (traversal, absolute paths, drive letters, UNC, NUL, look-alike
Unicode, links planted in the folder) must never yield a path outside the root, and must be
refused with the caller's own error, not an unrelated exception.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.security import approval as approval_module
from revit_mcp_server.security import proof as proof_mod
from revit_mcp_server.security.recipe_store import ID_RE as RECIPE_ID_RE
from revit_mcp_server.security.safe_paths import PLAN_ID_RE, SNAPSHOT_ID_RE, safe_child, snapshot_file
from revit_mcp_server.security.workspace import RESERVED_DIRS, WorkspaceMonitor

PATTERNS = {
    "plan": PLAN_ID_RE,
    "snapshot": SNAPSHOT_ID_RE,
    "proof": proof_mod._ID_RE,
    "recipe": RECIPE_ID_RE,
    "inflight": approval_module.INFLIGHT_KEY_RE,
    "claim": approval_module._CLAIM_NAME_RE,
    # Not used by the code: shows that steps 2 and 3 of safe_child hold on their own.
    "anything": re.compile(r".+", re.S),
}

FRAGMENTS = [
    "..", ".", "/", "\\", "C:", "c:\\", "C:/", "\\\\srv\\share\\", "//srv/share/", "\\\\?\\C:\\", "\x00",
    "\u202e", "\u2215", "\u2044", "\uff0e\uff0e", "\uff0f", "\u2024\u2024", "%2e%2e%2f", "~", " ", "\n", "\t",
    "con", "nul.txt", "a", "x.json", "plan_0123456789ab", "act_0123456789ab", "out", "dirlink", "loop", "rel",
    "inside", "\u0430", "\u00e9", "e\u0301", "::$DATA", "*", "?", "|",
]
hostile_names = st.one_of(
    st.lists(st.sampled_from(FRAGMENTS), min_size=1, max_size=6).map("".join),
    st.text(max_size=40),
    st.text(alphabet=st.characters(codec="utf-8"), max_size=12).map(lambda t: "../" + t),
)


class Refused(Exception):
    pass


def _refuse(reason: str) -> Exception:
    return Refused(reason)


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """root/ with a regular file and links that point out of it; outside/ next to it."""
    base = tmp_path_factory.mktemp("paths")
    root, outside = base / "root", base / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.json").write_text("{}")
    (root / "inside.json").write_text("{}")
    links = {
        "out.json": outside / "secret.json",
        "dirlink": outside,
        "rel.json": Path("..") / "outside" / "secret.json",
        "loop.json": root / "loop.json",
    }
    made = True
    for name, target in links.items():
        try:
            os.symlink(target, root / name)
        except (OSError, NotImplementedError):  # Windows without the symlink privilege
            made = False
    return {"root": root, "outside": outside, "links": made}


def _assert_child(result: Path, root: Path, subdir: Any = None) -> None:
    real_root = os.path.realpath(root)
    folder = os.path.join(real_root, subdir) if subdir else real_root
    assert os.path.dirname(str(result)) == folder
    assert str(result).startswith(os.path.join(real_root, ""))
    assert os.path.realpath(result) == str(result)  # no link left to follow


@given(name=hostile_names, kind=st.sampled_from(sorted(PATTERNS)), suffix=st.sampled_from([".json", ".lock", ""]),
       subdir=st.sampled_from([None, ".claims", "dirlink"]))
def test_safe_child_never_leaves_the_root(tree: dict, name: str, kind: str, suffix: str, subdir: Any) -> None:
    root = tree["root"]
    try:
        result = safe_child(root, name, suffix, PATTERNS[kind], _refuse, subdir=subdir)
    except Refused:
        return
    except ValueError as e:
        # Only the permissive pattern lets NUL through to the OS layer, which refuses it.
        assert kind == "anything" and "\x00" in name, e
        return
    _assert_child(result, root, subdir)
    assert subdir != "dirlink", "a linked subfolder was followed out of the root"


# Names that resolve to a direct child of root (the second goes out through the link and back in).
STAYS_INSIDE = ("inside", "dirlink/../root/inside", "loop")


@given(name=st.sampled_from(["out", "rel", "loop", "dirlink/secret", "dirlink/../root/inside", "dirlink/../outside/secret", "inside"]),
       kind=st.sampled_from(["snapshot", "anything"]))
def test_links_planted_in_the_folder_are_refused(tree: dict, name: str, kind: str) -> None:
    if not tree["links"]:
        pytest.skip("symlinks unavailable")
    root = tree["root"]
    try:
        result = safe_child(root, name, ".json", PATTERNS[kind], _refuse)
    except Refused:
        assert name != "inside"  # refusing is always safe; the plain file must still be usable
        return
    # A self-referencing link resolves to itself, inside the folder; opening it fails with ELOOP.
    assert name in STAYS_INSIDE
    _assert_child(result, root)


@given(name=hostile_names)
def test_snapshot_file_refuses_with_value_error_only(tree: dict, name: Any) -> None:
    try:
        result = snapshot_file(tree["root"], name)
    except ValueError as e:
        assert "snapshot_id" in str(e)
        return
    _assert_child(result, tree["root"])


@given(name=st.one_of(hostile_names, st.none(), st.integers(), st.binary(max_size=8)))
def test_plan_ids_refused_with_bridge_error(tree: dict, name: Any) -> None:
    from revit_mcp_server.errors import BridgeError
    gate = approval_module.ApprovalGate(tree["root"].parent / "gate-ws", "ask_first")
    for call in (lambda: approval_module.validate_plan_id(name), lambda: gate.load_plan(name)):
        try:
            call()
        except BridgeError:
            continue
        assert isinstance(name, str) and PLAN_ID_RE.fullmatch(name)


@given(rel=hostile_names, absolute=st.booleans())
def test_workspace_sandbox_never_admits_outside_or_reserved(tree: dict, rel: str, absolute: bool) -> None:
    root = tree["root"]
    monitor = WorkspaceMonitor([root])
    candidate = Path(rel) if absolute else root / rel
    try:
        resolved = monitor.assert_in_workspace(candidate)
    except WorkspaceViolation:
        return
    real_root = os.path.realpath(root)
    assert str(resolved) == real_root or str(resolved).startswith(os.path.join(real_root, ""))
    assert not any(str(resolved).startswith(os.path.join(real_root, d)) and
                   (len(str(resolved)) == len(os.path.join(real_root, d)) or
                    str(resolved)[len(os.path.join(real_root, d))] == os.sep) for d in RESERVED_DIRS)
