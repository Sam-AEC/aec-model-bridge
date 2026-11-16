from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from ..errors import WorkspaceViolation


# Folders the approval system owns. Tools must never write here: a plan, its claim
# files or its proof bundle could otherwise be overwritten or pre-created by a tool.
RESERVED_DIRS = ("plans", "proofs")


def _real(path: "Path | str") -> str:
    """Absolute, symlink-free, normalised form of ``path`` (it need not exist)."""
    return os.path.normpath(os.path.realpath(os.fspath(path)))


def _is_within(path: str, directory: str) -> bool:
    """True when ``path`` is ``directory`` or inside it. Both come from ``_real``;
    the comparison ignores case on Windows."""
    path, directory = os.path.normcase(path), os.path.normcase(directory)
    return path == directory or path.startswith(os.path.join(directory, ""))


def is_reserved_path(candidate: Path, base: Path) -> bool:
    candidate_real, base_real = _real(candidate), _real(base)
    return any(_is_within(candidate_real, os.path.join(base_real, name)) for name in RESERVED_DIRS)


class WorkspaceMonitor:
    def __init__(self, allowed_directories: Sequence[Path]):
        self.allowed_directories = [Path(_real(directory)) for directory in allowed_directories]

    def assert_in_workspace(self, candidate: Path) -> Path:
        resolved = _real(candidate)
        if not any(_is_within(resolved, os.fspath(directory)) for directory in self.allowed_directories):
            raise WorkspaceViolation(f"{resolved} is outside the allowed workspace directories")
        if any(is_reserved_path(Path(resolved), directory) for directory in self.allowed_directories):
            raise WorkspaceViolation(f"{resolved} is in a folder reserved for plans and proofs")
        return Path(resolved)
