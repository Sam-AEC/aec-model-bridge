"""Opt-in helper library for `revit_execute_python` scripts (`helpers: true`).

The helpers are IronPython source kept in this folder:

* ``amb_read.ipy``: collectors with quick filters, parameter rules (ElementParameterFilter), bounding-box and solid
  filters, unit conversion (UnitUtils with ForgeTypeId) and Element.GetDependentElements. It only reads the model and
  passes the read-mode text rules.
* ``amb_write.ipy``: one transaction per batch, SubTransaction per item, TransactionGroup with Assimilate, parameter
  writes. It names Transaction, so it is only sent in write mode, which needs an approved plan.

With ``helpers: true`` the server sends ``helpers + END_MARKER + script`` to the add-in. The caller's script is
appended unchanged. In read mode the caller's script is checked on its own and the combined text is checked again,
so the helpers cannot widen what read mode allows (security/read_mode.py). The add-in repeats its own text check on
the combined text and keeps its run-time backstop. Without the flag nothing is added.

The source is the subset of Python that IronPython 2.7 (Revit 2024) and IronPython 3.4 (Revit 2025 and later) both
accept; tests/test_python_helpers.py checks it. See docs/python-automation.md.

UNVERIFIED: the helpers have not run in a live Revit session.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

HELPERS_DIR = Path(__file__).resolve().parent
READ_HELPERS = HELPERS_DIR / "amb_read.ipy"
WRITE_HELPERS = HELPERS_DIR / "amb_write.ipy"
END_MARKER = "# ---- end of AEC Model Bridge helpers (amb); the caller's script starts on the next line ----"

# A `from __future__` import must be the first statement of a module, so it cannot follow the helpers.
_FUTURE_IMPORT = re.compile(r"^\s*from\s+__future__\s+import\b", re.MULTILINE)


def normalize_helpers(value: Any) -> bool:
    """None or missing means False. Only real booleans are accepted; anything else is an error (fail closed)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise ValueError(f"helpers must be true or false, got {value!r}")


@lru_cache(maxsize=2)
def helper_source(mode: str) -> str:
    """Helper text for a mode: the read part, plus the write part in write mode."""
    parts = [READ_HELPERS.read_text(encoding="utf-8")]
    if mode == "write":
        parts.append(WRITE_HELPERS.read_text(encoding="utf-8"))
    elif mode != "read":
        raise ValueError(f"mode must be 'read' or 'write', got {mode!r}")
    return "\n\n".join(part.rstrip("\n") for part in parts).replace("\r\n", "\n") + "\n"


def helper_line_count(mode: str) -> int:
    """Lines the server puts before the caller's script; subtract it from line numbers in error messages."""
    return helper_source(mode).count("\n") + 1


def helper_sha256(mode: str) -> str:
    return hashlib.sha256(helper_source(mode).encode("utf-8")).hexdigest()


def with_helpers(script: Any, mode: str) -> str:
    """Return the helper text, the end marker and the caller's script. Refuses what cannot follow a prelude."""
    if not isinstance(script, str) or not script.strip():
        raise ValueError("helpers=true needs a non-empty script string")
    if _FUTURE_IMPORT.search(script):
        raise ValueError(
            "helpers=true cannot be used with a 'from __future__' import, because the helpers come first. "
            "Remove the import (print(x) with one argument works on IronPython 2.7 and 3.4) or call without helpers."
        )
    return helper_source(mode) + END_MARKER + "\n" + script
