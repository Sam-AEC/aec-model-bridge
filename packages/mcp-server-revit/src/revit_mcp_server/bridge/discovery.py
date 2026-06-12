import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
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


def discover_switches(registry_dir: Path = REGISTRY_DIR) -> Dict[str, SwitchInfo]:
    """
    Scans the registry directory for valid switch files.
    Prunes stale files.
    Returns a dict mapping provider_id to SwitchInfo.
    """
    switches: Dict[str, SwitchInfo] = {}

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

