from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..errors import WorkspaceViolation


# Folders the approval system owns. Tools must never write here: a plan, its claim
# files or its proof bundle could otherwise be overwritten or pre-created by a tool.
RESERVED_DIRS = ("plans", "proofs")


def is_reserved_path(candidate: Path, base: Path) -> bool:
    base = Path(base).resolve()
    candidate = Path(candidate).resolve()
    return any(candidate.is_relative_to(base / name) for name in RESERVED_DIRS)


class WorkspaceMonitor:
    def __init__(self, allowed_directories: Sequence[Path]):
        self.allowed_directories = [directory.resolve() for directory in allowed_directories]

    def assert_in_workspace(self, candidate: Path) -> Path:
        candidate = candidate.resolve()
        if not any(candidate.is_relative_to(directory) for directory in self.allowed_directories):
            raise WorkspaceViolation(f"{candidate} is outside the allowed workspace directories")
        if any(is_reserved_path(candidate, directory) for directory in self.allowed_directories):
            raise WorkspaceViolation(f"{candidate} is in a folder reserved for plans and proofs")
        return candidate
