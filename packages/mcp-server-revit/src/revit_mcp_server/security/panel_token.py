"""Per-user access token for the panel hub (panel_server.py, 127.0.0.1:8787).

One secret per Windows user, shared by every Revit instance and the hub they share.
The first hub to start creates the file; every later hub, and the Revit add-in's
HubClient, reads the same file. The token proves "a local process running as this
user"; it does not prove a human is present (see docs/security.md).

File: ``%LOCALAPPDATA%\\AECModelBridge\\panel-hub.token`` (same directory as the add-in's
``registry`` folder). ``MCP_PANEL_TOKEN_FILE`` overrides the path (tests, unusual installs).

Rules this module enforces:

* 32 random bytes, ``secrets.token_urlsafe(32)`` (43 URL-safe characters).
* Created atomically and never overwritten: a temp file is written with mode 0600
  (POSIX) or an owner-only ACL (Windows, ``icacls``), then hard-linked to the final
  name. ``link`` fails if the name exists, so two hubs starting together end up with
  one file and one token.
* Read back strictly: POSIX refuses a symlink, a file owned by someone else, or any
  group/other permission bit. Windows relies on the owner-only ACL set at creation
  (not re-verified on read).
* The token is never logged and never put in an error message. ``redact_data`` and the
  hub's log file mask it too (``register_secret_value``).

Rotation: delete the file and restart every hub; the next hub writes a new token and
the add-in re-reads it. A running hub keeps the token it started with.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from .audit import register_secret_value

logger = logging.getLogger(__name__)

TOKEN_FILENAME = "panel-hub.token"
TOKEN_ENV_FILE = "MCP_PANEL_TOKEN_FILE"
TOKEN_HEADER = "X-AMB-Token"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_READ_RETRIES = 20
_READ_RETRY_DELAY = 0.05


class PanelTokenError(RuntimeError):
    """The token file is unusable. The message never contains the token."""


def token_path() -> Path:
    override = os.environ.get(TOKEN_ENV_FILE)
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "AECModelBridge" / TOKEN_FILENAME


def is_valid_token(value: str) -> bool:
    return bool(_TOKEN_RE.fullmatch(value))


def _restrict_windows_acl(path: Path) -> None:
    user = os.environ.get("USERNAME")
    if not user:
        raise PanelTokenError("Cannot restrict the panel token file: USERNAME is not set.")
    domain = os.environ.get("USERDOMAIN")
    principal = f"{domain}\\{user}" if domain else user
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:(F)"],
            check=True, capture_output=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise PanelTokenError(f"Could not restrict access to the panel token file ({type(e).__name__}).") from None


def _check_posix_file(path: Path) -> None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise
    except OSError as e:
        raise PanelTokenError(f"Cannot inspect the panel token file {path}: {e.strerror or e}") from None
    import stat

    if not stat.S_ISREG(st.st_mode):
        raise PanelTokenError(f"The panel token file {path} is not a regular file; delete it and restart the hub.")
    if st.st_uid != os.getuid():
        raise PanelTokenError(f"The panel token file {path} is owned by another user; delete it and restart the hub.")
    if st.st_mode & 0o077:
        raise PanelTokenError(
            f"The panel token file {path} is accessible to other users (mode {stat.S_IMODE(st.st_mode):04o}). "
            "Refusing to use it. Delete it and restart the hub to create a new one."
        )


def read_token(path: Path | None = None) -> str | None:
    """Return the stored token, or None if the file does not exist.

    Raises PanelTokenError if the file exists but is unsafe or malformed. A file that is
    momentarily empty (another hub is between create and write) is retried briefly.
    """
    path = path or token_path()
    for attempt in range(_READ_RETRIES):
        if os.name != "nt":
            try:
                _check_posix_file(path)
            except FileNotFoundError:
                return None
        try:
            raw = path.read_text(encoding="ascii")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError):
            raise PanelTokenError(f"The panel token file {path} cannot be read; delete it and restart the hub.") from None
        value = raw.strip()
        if is_valid_token(value):
            register_secret_value(value)
            return value
        if value or attempt == _READ_RETRIES - 1:
            break
        time.sleep(_READ_RETRY_DELAY)
    raise PanelTokenError(f"The panel token file {path} is malformed; delete it and restart the hub.")


def _create_token_file(path: Path) -> None:
    """Write a new token file with owner-only access. No-op if it already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    register_secret_value(token)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write((token + "\n").encode("ascii"))
            fh.flush()
            os.fsync(fh.fileno())
        if os.name == "nt":
            _restrict_windows_acl(tmp)
        else:
            os.chmod(tmp, 0o600)
        try:
            os.link(tmp, path)  # fails if path exists: first writer wins, nobody is overwritten
        except FileExistsError:
            return
        except OSError:
            # Filesystem without hard links: exclusive create of the final name instead
            # (a concurrent reader may see it empty; read_token retries for that).
            _exclusive_copy(path, token)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _exclusive_copy(path: Path, token: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as fh:
        fh.write((token + "\n").encode("ascii"))
    if os.name == "nt":
        _restrict_windows_acl(path)


def load_or_create_token(path: Path | None = None) -> str:
    """Return the per-user token, creating the file if this is the first hub to start."""
    path = path or token_path()
    existing = read_token(path)
    if existing is not None:
        return existing
    _create_token_file(path)
    created = read_token(path)
    if created is None:  # pragma: no cover - vanished between create and read
        raise PanelTokenError(f"The panel token file {path} could not be created.")
    logger.info("Created the panel hub token file")
    return created


if __name__ == "__main__":  # pragma: no cover
    # Not a way to print the token: only reports whether a usable file exists.
    try:
        print("token file:", "present" if read_token() else "absent")
    except PanelTokenError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
