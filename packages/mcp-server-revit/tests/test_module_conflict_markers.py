"""No module file may contain a merge conflict marker."""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
MODULES = TESTS.parent / "src" / "revit_mcp_server" / "modules"
MARKER = re.compile(r"^(<{7}|={7}|>{7})( |$)")
# The sparing test files and stub were scanned by the old per-module test; keep them in scope.
EXTRA = [TESTS / "test_revit_sparing.py", TESTS / "test_revit_sparing_scripts.py", TESTS / "revit_sparing_stub.py"]


def test_module_files_have_no_conflict_markers():
    paths = sorted([*MODULES.rglob("*"), *EXTRA])
    scanned = 0
    for path in paths:
        if path.is_file() and path.suffix in {".py", ".json", ".ipy"}:
            scanned += 1
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                assert not MARKER.match(line), f"{path.relative_to(TESTS.parent)}:{number}"
    assert scanned > 50, "modules/ walk found too few files"
