import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List
import ctypes

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Constants
REGISTRY_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "AECModelBridge" / "registry"
MAX_STALE_AGE_DAYS = 7


class SwitchInfo(BaseModel):
    provider_id: str
    endpoint: str
    pid: int
    host_version: str
    connector_version: str
    protocol_version: int
    capability_digest: str
    session_token: str
    started_at: str


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is currently running on Windows."""
    # 0x0400 is PROCESS_QUERY_INFORMATION
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400, False, pid)
        if handle == 0:
            return False
        # Get exit code to ensure it hasn't terminated
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == 259  # 259 is STILL_ACTIVE
    except Exception as e:
        logger.debug("PID check failed for %s: %s", pid, e)
        return False


PID_REUSE_TOLERANCE_SECONDS = 30


def process_start_time(pid: int) -> datetime | None:
    """Start time of a running process (UTC), or None when it cannot be determined."""
    try:
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                created, exited, kernel, user = (ctypes.c_ulonglong() for _ in range(4))
                if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                                ctypes.byref(kernel), ctypes.byref(user)):
                    return None
                # FILETIME: 100 ns ticks since 1601-01-01
                return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=created.value // 10)
            finally:
                kernel32.CloseHandle(handle)
    except Exception as e:  # best effort only
        logger.debug("Process start time unavailable for %s: %s", pid, e)
    return None


def is_live_instance(info: SwitchInfo) -> bool:
    """True when the entry's process is alive and is not a recycled pid.

    No age limit: a Revit session that has been open for weeks is still live. The bridge server starts
    after its Revit process, so a process that started AFTER the registry's ``started_at`` (beyond a
    tolerance) cannot be the one that wrote the entry. If the start time cannot be read, the pid check
    alone decides.
    """
    if not is_pid_alive(info.pid):
        return False
    try:
        registered = datetime.fromisoformat(info.started_at.replace("Z", "+00:00"))
        if registered.tzinfo is None:
            registered = registered.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    actual = process_start_time(info.pid)
    if actual is not None and (actual - registered).total_seconds() > PID_REUSE_TOLERANCE_SECONDS:
        return False
    return True


def _is_stale(info: SwitchInfo) -> bool:
    """A registry entry is stale if the PID is dead, or it is older than 7 days."""
    try:
        started_at = datetime.fromisoformat(info.started_at.replace('Z', '+00:00'))
        age_days = (datetime.now(timezone.utc) - started_at).days
        if age_days > MAX_STALE_AGE_DAYS:
            return True
    except ValueError:
        pass
    
    return not is_pid_alive(info.pid)


def discover_switches(registry_dir: Path | None = None) -> Dict[str, SwitchInfo]:
    """
    Scans the registry directory for valid switch files.
    Prunes stale files.
    Returns a dict mapping provider_id to SwitchInfo.
    """
    switches: Dict[str, SwitchInfo] = {}
    registry_dir = registry_dir or REGISTRY_DIR

    if not registry_dir.exists():
        return switches

    for file_path in registry_dir.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            info = SwitchInfo(**data)
            
            if _is_stale(info):
                logger.info("Pruning stale switch registry entry: %s", file_path)
                try:
                    file_path.unlink()
                except OSError as e:
                    logger.warning("Failed to delete stale entry %s: %s", file_path, e)
                continue
            
            # Prefer the most recently started switch for a given provider
            if info.provider_id in switches:
                existing = switches[info.provider_id]
                try:
                    existing_start = datetime.fromisoformat(existing.started_at.replace('Z', '+00:00'))
                    new_start = datetime.fromisoformat(info.started_at.replace('Z', '+00:00'))
                    if new_start > existing_start:
                        switches[info.provider_id] = info
                except ValueError:
                    switches[info.provider_id] = info
            else:
                switches[info.provider_id] = info

        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Malformed registry entry %s: %s", file_path, e)
        except PermissionError as e:
            logger.warning("ACL denied access to registry entry %s: %s", file_path, e)
        except Exception as e:
            logger.error("Unexpected error reading %s: %s", file_path, e)

    return switches


def discover_switch_list(registry_dir: Path | None = None, *, prune: bool = True) -> List[SwitchInfo]:
    """Return every live switch entry, sorted from newest to oldest.

    ``prune=True`` (default) deletes stale files (dead pid, or older than 7 days). ``prune=False`` is for
    routing on a read path: nothing is deleted or age-filtered; an entry is kept when its process is alive
    and not a recycled pid (``is_live_instance``), so a Revit open for weeks stays routable.
    """
    switches: List[SwitchInfo] = []
    registry_dir = registry_dir or REGISTRY_DIR

    if not registry_dir.exists():
        return switches

    for file_path in registry_dir.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            info = SwitchInfo(**data)

            if not prune:
                if is_live_instance(info):
                    switches.append(info)
                continue

            if _is_stale(info):
                logger.info("Pruning stale switch registry entry: %s", file_path)
                try:
                    file_path.unlink()
                except OSError as e:
                    logger.warning("Failed to delete stale entry %s: %s", file_path, e)
                continue

            switches.append(info)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Malformed registry entry %s: %s", file_path, e)
        except PermissionError as e:
            logger.warning("ACL denied access to registry entry %s: %s", file_path, e)
        except Exception as e:
            logger.error("Unexpected error reading %s: %s", file_path, e)

    def started_at(info: SwitchInfo) -> datetime:
        try:
            return datetime.fromisoformat(info.started_at.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    return sorted(switches, key=started_at, reverse=True)


def select_switch(
    provider_id: str = "revit",
    host_version: str | None = None,
    registry_dir: Path | None = None,
) -> SwitchInfo | None:
    """Select the newest live switch for a provider, optionally by host version."""
    requested_version = host_version.strip().lower() if host_version else None
    for switch in discover_switch_list(registry_dir):
        if switch.provider_id != provider_id:
            continue
        switch_version = switch.host_version.lower()
        if requested_version and switch_version != requested_version and not switch_version.startswith(requested_version):
            continue
        return switch
    return None


def available_host_versions(provider_id: str = "revit", registry_dir: Path | None = None) -> List[str]:
    """Return live host versions for a provider, sorted newest first without duplicates."""
    versions: List[str] = []
    for switch in discover_switch_list(registry_dir):
        if switch.provider_id != provider_id:
            continue
        if switch.host_version not in versions:
            versions.append(switch.host_version)
    return versions

