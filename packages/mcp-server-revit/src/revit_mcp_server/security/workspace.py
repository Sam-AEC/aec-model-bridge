from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from ..errors import WorkspaceViolation


# Folders the approval system owns. Tools must never write here: a plan, its claim
# files or its proof bundle could otherwise be overwritten or pre-created by a tool.
RESERVED_DIRS = ("plans", "proofs")


def _real(path: "Path | str") -> str:
    """Absolute, symlink-free, normalised form of ``path`` (it need not exist).

    A NUL character is refused as a sandbox violation; the OS layer would raise a bare ValueError."""
    text = os.fspath(path)
    if "\x00" in str(text):
        raise WorkspaceViolation("The path contains a NUL character; refusing it.")
    return os.path.normpath(os.path.realpath(text))


def _fold(path: str, casefold: "bool | None") -> str:
    """``None`` follows the OS (``os.path.normcase``: case-insensitive on Windows only).
    ``True`` or ``False`` forces the choice so tests can cover both on any OS."""
    if casefold is None:
        return os.path.normcase(path)
    return path.casefold() if casefold else path


def _is_within(path: str, directory: str, casefold: "bool | None" = None) -> bool:
    """True when ``path`` is ``directory`` or inside it. Both come from ``_real``;
    the comparison ignores case on Windows (or when ``casefold`` is True)."""
    path, directory = _fold(path, casefold), _fold(directory, casefold)
    return path == directory or path.startswith(os.path.join(directory, ""))


def is_reserved_path(candidate: Path, base: Path, casefold: "bool | None" = None) -> bool:
    candidate_real, base_real = _real(candidate), _real(base)
    return any(_is_within(candidate_real, os.path.join(base_real, name), casefold) for name in RESERVED_DIRS)


class WorkspaceMonitor:
    def __init__(self, allowed_directories: Sequence[Path], casefold: "bool | None" = None):
        self._casefold = casefold
        self.allowed_directories = [Path(_real(directory)) for directory in allowed_directories]

    def assert_in_workspace(self, candidate: Path) -> Path:
        resolved = _real(candidate)
        if not any(_is_within(resolved, os.fspath(directory), self._casefold) for directory in self.allowed_directories):
            raise WorkspaceViolation(f"{resolved} is outside the allowed workspace directories")
        if any(is_reserved_path(Path(resolved), directory, self._casefold) for directory in self.allowed_directories):
            raise WorkspaceViolation(f"{resolved} is in a folder reserved for plans and proofs")
        return Path(resolved)
