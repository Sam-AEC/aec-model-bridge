"""Signed approval records (issue #313).

A plan's approval fields (``state``, ``approved_hash`` ...) live in a JSON file under the
workspace ``plans/`` folder. The workspace sandbox reserves that folder from tool writes,
but any local process that can write the file could mark a plan approved. So every
approval is signed, and every gated write that relies on a plan verifies the signature.

What is signed: HMAC-SHA256 over a canonical JSON encoding of the approval record:
``plan_id``, ``approved_hash``, the approval state (always ``"approved"``; the plan's live
state is checked separately), ``approved_via`` (the channel), ``approved_by``,
``approved_at`` and, when the plan has one, its document ``binding``. The MAC is stored on
the plan as ``approval_sig`` = ``{"v": 1, "alg": "HMAC-SHA256", "mac": <hex>}``.

The key:

* 32 bytes from ``secrets.token_bytes(32)``, generated once per workspace on the first
  approval, at ``plans/.keys/approval-signing.key`` (inside the reserved area, so no
  file tool can read or write it).
* Created atomically with mode 0600 and never overwritten (two processes approving at
  the same time end up with one key). On POSIX a key file that is a symlink, owned by
  another user, or readable by group or others is refused.
* On Windows file modes do not apply. The key relies on the workspace being in the
  user's profile (the default is ``~/Documents/AEC Model Bridge``), where other
  standard users have no access. UNVERIFIED on a live Windows install.
* Never logged, never put in an error message, never returned by any tool.

Verification fails closed: a missing signature (plans approved before this change), a
missing or unreadable key, a different key, or any edited signed field gives the same
plain error, ``NOT_VERIFIED_MESSAGE``. The fix is always the same: approve it again.

Rotation: delete the key file. Every approved plan that has not run must then be
approved again.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..errors import BridgeError

logger = logging.getLogger(__name__)

SIGNATURE_KEY = "approval_sig"
SIGNATURE_VERSION = 1
SIGNATURE_ALG = "HMAC-SHA256"
KEY_SUBDIR = ".keys"
KEY_FILENAME = "approval-signing.key"
KEY_BYTES = 32
NOT_VERIFIED_MESSAGE = "This plan's approval record does not verify; approve it again."

_READ_RETRIES = 20
_READ_RETRY_DELAY = 0.05


class ApprovalKeyError(BridgeError):
    """The signing key file is unusable. The message never contains the key."""


def key_path(plans_dir: Path) -> Path:
    return Path(plans_dir) / KEY_SUBDIR / KEY_FILENAME


def _check_posix_stat(st: os.stat_result) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise ApprovalKeyError("The approval signing key is not a regular file.")
    if st.st_uid != os.getuid():
        raise ApprovalKeyError("The approval signing key is owned by another user.")
    if st.st_mode & 0o077:
        raise ApprovalKeyError("The approval signing key is readable by other users; refusing to use it.")


def _read_key_file(path: Path) -> bytes:
    if os.name == "nt":  # pragma: no cover - Windows
        with open(path, "rb") as fh:
            return fh.read(KEY_BYTES + 1)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise
    except OSError:
        raise ApprovalKeyError("The approval signing key cannot be opened (a symlink is not accepted).") from None
    try:
        _check_posix_stat(os.fstat(fd))
        return os.read(fd, KEY_BYTES + 1)
    finally:
        os.close(fd)


def load_key(plans_dir: Path) -> Optional[bytes]:
    """The workspace key, or None when no key file exists. Raises ApprovalKeyError when the
    file exists but is unsafe or malformed. A file that is momentarily empty (another process
    is between create and write) is retried briefly."""
    path = key_path(plans_dir)
    for attempt in range(_READ_RETRIES):
        try:
            data = _read_key_file(path)
        except FileNotFoundError:
            return None
        except OSError:
            raise ApprovalKeyError("The approval signing key cannot be read.") from None
        if len(data) == KEY_BYTES:
            return data
        if data or attempt == _READ_RETRIES - 1:
            break
        time.sleep(_READ_RETRY_DELAY)
    raise ApprovalKeyError("The approval signing key is malformed.")


def _create_key_file(path: Path) -> None:
    """Write a new key with owner-only access. Leaves an existing key untouched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = getattr(os, "O_BINARY", 0) | os.O_WRONLY | os.O_CREAT | os.O_EXCL
    key = secrets.token_bytes(KEY_BYTES)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        try:
            os.link(tmp, path)  # fails if the key exists: first writer wins, nothing is overwritten
        except FileExistsError:
            return
        except OSError:  # pragma: no cover - filesystem without hard links
            try:
                out = os.open(path, flags, 0o600)
            except FileExistsError:
                return
            with os.fdopen(out, "wb") as fh:
                fh.write(key)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def load_or_create_key(plans_dir: Path) -> bytes:
    key = load_key(plans_dir)
    if key is not None:
        return key
    _create_key_file(key_path(plans_dir))
    key = load_key(plans_dir)
    if key is None:  # pragma: no cover - vanished between create and read
        raise ApprovalKeyError("The approval signing key could not be created.")
    logger.info("Created the approval signing key for this workspace")
    return key


def approval_record(plan: Dict[str, Any]) -> bytes:
    """Canonical bytes of the signed approval record. Raises TypeError/ValueError for
    content that cannot be encoded (treated as 'does not verify')."""
    record: Dict[str, Any] = {
        "v": SIGNATURE_VERSION,
        "plan_id": plan.get("plan_id"),
        "approved_hash": plan.get("approved_hash"),
        "state": "approved",
        "approved_via": plan.get("approved_via"),
        "approved_by": plan.get("approved_by"),
        "approved_at": plan.get("approved_at"),
    }
    if "binding" in plan:
        record["binding"] = plan["binding"]
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _mac(key: bytes, plan: Dict[str, Any]) -> str:
    return hmac.new(key, approval_record(plan), hashlib.sha256).hexdigest()


def sign_plan(plans_dir: Path, plan: Dict[str, Any]) -> None:
    """Set ``plan[SIGNATURE_KEY]`` for the approval fields already on ``plan``. Creates the
    workspace key on first use. Raises ApprovalKeyError when the key is unusable."""
    plan[SIGNATURE_KEY] = {"v": SIGNATURE_VERSION, "alg": SIGNATURE_ALG,
                           "mac": _mac(load_or_create_key(plans_dir), plan)}


def verify_plan_signature(plans_dir: Path, plan: Dict[str, Any]) -> bool:
    """True only when the plan carries a signature that verifies under this workspace's key.
    Never raises and never creates a key."""
    sig = plan.get(SIGNATURE_KEY) if isinstance(plan, dict) else None
    if not isinstance(sig, dict) or sig.get("v") != SIGNATURE_VERSION or sig.get("alg") != SIGNATURE_ALG:
        return False
    given = sig.get("mac")
    if not isinstance(given, str):
        return False
    try:
        key = load_key(plans_dir)
    except ApprovalKeyError as e:
        logger.warning("Approval signing key unusable: %s", e)
        return False
    if key is None:
        return False
    try:
        expected = _mac(key, plan)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected.encode("ascii"), given.encode("ascii", "replace"))


def require_signed(plans_dir: Path, plan: Dict[str, Any]) -> None:
    """Raise BridgeError(NOT_VERIFIED_MESSAGE) unless the approval record verifies."""
    if not verify_plan_signature(plans_dir, plan):
        raise BridgeError(NOT_VERIFIED_MESSAGE)
