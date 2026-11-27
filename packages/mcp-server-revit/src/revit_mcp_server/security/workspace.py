from __future__ import annotations

import os
from contextvars import ContextVar
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


# Folders the connected AI client has open (MCP roots), as real paths, for the request being served.
# None means the client declared none: the configured directories apply unchanged. An empty tuple
# means it declared roots that cannot be used. Set per request by mcp_server; see client_roots.py.
CLIENT_ROOTS: "ContextVar[tuple[str, ...] | None]" = ContextVar("client_roots", default=None)


def narrow_directories(
    allowed: Sequence["Path | str"], roots: Sequence[str], casefold: "bool | None" = None,
    allowed_resolved: bool = False,
) -> "tuple[list[Path], list[str]]":
    """The intersection of the allowed directories and the client roots, plus the roots left out.

    A root inside an allowed directory narrows to that root. A root that contains an allowed
    directory leaves that directory as it is. A root that touches no allowed directory is ignored.
    The result is never larger than ``allowed``. ``allowed_resolved`` says ``allowed`` already holds
    real paths (as ``WorkspaceMonitor`` keeps them), so they are not resolved again; roots always are."""
    allowed_real = [os.fspath(d) for d in allowed] if allowed_resolved else [_real(d) for d in allowed]
    kept: list[str] = []
    ignored: list[str] = []
    for root in roots:
        root_real = _real(root)
        hit = False
        for directory in allowed_real:
            if _is_within(root_real, directory, casefold):
                kept.append(root_real)
                hit = True
            elif _is_within(directory, root_real, casefold):
                kept.append(directory)
                hit = True
        if not hit:
            ignored.append(root_real)
    return [Path(p) for p in dict.fromkeys(kept)], ignored


class WorkspaceMonitor:
    def __init__(self, allowed_directories: Sequence[Path], casefold: "bool | None" = None):
        self._casefold = casefold
        self.allowed_directories = [Path(_real(directory)) for directory in allowed_directories]

    def effective_directories(self) -> "list[Path]":
        """The allowed directories, narrowed to the current client's roots when it declared any."""
        roots = CLIENT_ROOTS.get()
        if roots is None:
            return self.allowed_directories
        return narrow_directories(self.allowed_directories, roots, self._casefold, allowed_resolved=True)[0]

    def assert_in_workspace(self, candidate: Path) -> Path:
        resolved = _real(candidate)
        directories = self.effective_directories()
        narrowed = CLIENT_ROOTS.get() is not None
        if narrowed and not directories:
            raise WorkspaceViolation(
                "The AI client's open folders (roots) do not overlap the allowed workspace directories, "
                "so file paths are refused. Open a folder inside the workspace in the client, or ask "
                "the administrator to change the allowed directories."
            )
        if not any(_is_within(resolved, os.fspath(directory), self._casefold) for directory in directories):
            where = " (limited to the folders the AI client has open)" if narrowed else ""
            raise WorkspaceViolation(f"{resolved} is outside the allowed workspace directories{where}")
        if any(is_reserved_path(Path(resolved), directory, self._casefold) for directory in self.allowed_directories):
            raise WorkspaceViolation(f"{resolved} is in a folder reserved for plans and proofs")
        return Path(resolved)
