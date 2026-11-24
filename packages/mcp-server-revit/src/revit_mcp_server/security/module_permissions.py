"""The one canonical list of module permissions (issue #157).

Manifests (``module.json``) may only declare these names; ``docs/module-authoring.md``
lists exactly the same set (a test compares them).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from ..errors import WorkspaceViolation

logger = logging.getLogger(__name__)

MODULE_PERMISSIONS = {
    "model.read": "standard read tools",
    "model.write": "tools that change the model (always behind the approval gate)",
    "model.delete": "destructive operations",
    "params.write": "parameter value changes",
    "files.write": "writing files inside the sandboxed workspace",
    "net.local": "local connections",
    "net.cloud": "cloud sync",
    "python.host": "raw Python on the host (off unless allow_python_host is True)",
}

# "enforce": a command without files.write is refused by workspace.assert_writable.
# "warn": it is only logged (an escape hatch for third-party modules).
PERMISSION_MODES = ("enforce", "warn")


def unknown_permissions(names: Iterable[str]) -> list[str]:
    return sorted({n for n in names if n not in MODULE_PERMISSIONS})


class ModuleWorkspace:
    """The workspace a module handler receives: the real workspace plus ``assert_writable``.

    Every other attribute (``allowed_directories``, ``assert_in_workspace``) passes through unchanged.
    """

    def __init__(self, workspace: Any, granted: Iterable[str], label: str, mode: str = "enforce"):
        self._workspace = workspace
        self._granted = frozenset(granted)
        self._label = label
        self._mode = mode if mode in PERMISSION_MODES else "enforce"

    def __getattr__(self, name: str) -> Any:
        return getattr(self._workspace, name)

    def assert_writable(self, candidate: Path) -> Path:
        """``assert_in_workspace`` for a path the module is about to write. Needs ``files.write``."""
        if "files.write" not in self._granted:
            message = f"'{self._label}' writes files but its manifest does not grant 'files.write'"
            if self._mode == "enforce":
                raise WorkspaceViolation(message)
            logger.warning("%s (warn mode: allowed)", message)
        return self._workspace.assert_in_workspace(Path(candidate))
