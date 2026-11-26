"""Atheris harness: safe_child and snapshot_file must stay inside the root or refuse.

Run: python fuzz/fuzz_safe_paths.py -max_total_time=60   (needs `atheris`, Linux or macOS)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from revit_mcp_server.security.safe_paths import SNAPSHOT_ID_RE, safe_child, snapshot_file

ROOT = Path(tempfile.mkdtemp(prefix="aec-fuzz-")).resolve()


class Refused(Exception):
    pass


def _refuse(reason: str) -> Exception:
    return Refused(reason)


def test_one_input(data: bytes) -> None:
    name = atheris.FuzzedDataProvider(data).ConsumeUnicodeNoSurrogates(64)
    try:
        result = safe_child(ROOT, name, ".json", SNAPSHOT_ID_RE, _refuse)
    except Refused:
        pass
    else:
        assert os.path.dirname(str(result)) == str(ROOT), result
    try:
        snapshot_file(ROOT, name)
    except ValueError:
        pass


if __name__ == "__main__":
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
