from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from enum import Enum
from json import JSONDecodeError
from pathlib import Path
from typing import Any, List

from dotenv import load_dotenv
from pydantic import DirectoryPath, Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources.providers import env as env_source

# Load .env file - search in multiple locations
# 1. Repository root (when running from source)
# 2. Current working directory
# 3. Package directory
_possible_locations = [
    Path(__file__).parent.parent.parent.parent.parent / ".env",  # repo root from package
    Path.cwd() / ".env",  # current directory
    Path(__file__).parent.parent.parent / ".env",  # package root
]

_env_loaded = False
for _env_file in _possible_locations:
    if _env_file.exists():
        load_dotenv(_env_file)
        _env_loaded = True
        break

if not _env_loaded:
    # Last resort: try loading from current directory without checking existence
    load_dotenv()


class BridgeMode(str, Enum):
    mock = "mock"
    bridge = "bridge"
    # Serves responses from a recorded cassette (MCP_REVIT_CASSETTE); never contacts Revit.
    replay = "replay"


class _RawEnvSource(env_source.EnvSettingsSource):
    def decode_complex_value(self, field_name, field, value):
        try:
            return super().decode_complex_value(field_name, field, value)
        except JSONDecodeError:
            return value


def default_workspace_dir() -> Path:
    """Zero-config workspace: ``~/Documents/AEC Model Bridge`` (not created here)."""
    return Path.home() / "Documents" / "AEC Model Bridge"


APPROVAL_MODES = ("look_only", "ask_first", "auto")
_APPROVAL_MODE_ALIASES = {"look_only": "look_only", "ask_first": "ask_first", "required": "ask_first", "auto": "auto"}
_config_logger = logging.getLogger(__name__)


def normalize_approval_mode(value: Any) -> str:
    """Return 'look_only', 'ask_first' or 'auto'.

    'required' is the older name for 'ask_first'. Fails closed: anything that is not
    an explicit, known mode (typos, empty, None) becomes 'ask_first' and logs a warning.
    Only an explicit 'auto' turns the approval gate off.
    """
    text = value.strip().lower() if isinstance(value, str) else ""
    mode = _APPROVAL_MODE_ALIASES.get(text)
    if mode is None:
        _config_logger.warning(
            "Unknown approval_mode %r; treating it as 'ask_first'. Valid values: look_only, ask_first "
            "(alias: required), auto. Only 'auto' turns the approval gate off.",
            value,
        )
        return "ask_first"
    return mode


APPROVAL_TTL_DEFAULT = 8 * 3600
PENDING_TTL_DEFAULT = 14 * 86400


def normalize_ttl(value: Any, default: int, name: str = "ttl") -> int:
    """Whole seconds, 0 disables. A negative, fractional, non-numeric or boolean value falls back to
    ``default`` (the restrictive choice) and logs a warning; it never turns expiry off."""
    try:
        if isinstance(value, bool):
            raise ValueError
        seconds = Decimal(str(value).strip())
        if not seconds.is_finite() or seconds < 0 or seconds != seconds.to_integral_value():
            raise ValueError
        return int(seconds)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        _config_logger.warning("Invalid %s %r; using the default of %d seconds. Use 0 to disable.", name, value, default)
        return default


_MCP_APPS_ALIASES = {
    "auto": "auto", "always": "always", "off": "off",
    # Older true/false values: true was the default, which is now auto.
    "true": "auto", "1": "auto", "yes": "auto", "on": "auto",
    "false": "off", "0": "off", "no": "off",
}


def normalize_mcp_apps(value) -> str:
    """MCP_REVIT_MCP_APPS: auto (default), always or off. true and false still work (auto, off)."""
    if value is None:
        return "auto"
    if isinstance(value, bool):
        return "auto" if value else "off"
    text = str(value).strip().lower()
    if text == "":
        return "auto"
    if text not in _MCP_APPS_ALIASES:
        raise ValueError(f"MCP_REVIT_MCP_APPS must be auto, always or off, not '{value}'.")
    return _MCP_APPS_ALIASES[text]


class Config(BaseSettings):
    # Both default safely so a one-click install works with no configuration.
    # An explicit MCP_REVIT_* value always wins. The default directory is only
    # created on demand by ensure_workspace(), never at import time.
    workspace_dir: Path = Field(default_factory=default_workspace_dir)
    allowed_directories: List[DirectoryPath] = Field(default_factory=list)
    bridge_url: str | None = Field(default=None)
    host_version: str | None = Field(default=None)
    # "http" (default) or "pipe" (ADR 0021). Unset falls back to AEC_BRIDGE_TRANSPORT, then "http".
    bridge_transport: str | None = Field(default=None)
    mode: BridgeMode = Field(default=BridgeMode.mock)
    audit_log: Path = Field(default_factory=lambda: Path("audit.log"))
    log_level: str = Field("INFO")
    approval_mode: str = Field(default="ask_first")
    approval_ttl: int = Field(default=APPROVAL_TTL_DEFAULT)  # seconds an approval stays usable; 0 = no limit
    pending_ttl: int = Field(default=PENDING_TTL_DEFAULT)  # seconds a draft stays approvable; 0 = no limit
    enable_user_modules: bool = Field(default=False)
    allow_python_host: bool = Field(default=False)
    module_permission_mode: str = Field(default="enforce")  # "enforce" or "warn" for files.write (issue #157)
    anthropic_api_key: str | None = Field(default=None)
    # MCP Apps plan review view (ui://aec-model-bridge/plan-review) and its tool _meta; read-only.
    # auto: _meta.ui only for clients that declare the extension; always; off.
    mcp_apps: str = Field(default="auto")

    _auto_dirs: List[Path] = PrivateAttr(default_factory=list)

    model_config = SettingsConfigDict(
        env_prefix="MCP_REVIT_",
        case_sensitive=False,
        extra="forbid",
    )

    @field_validator("bridge_url", mode="before")
    def ignore_legacy_default_bridge_url(cls, value):
        """An empty value, or the old shipped default http://127.0.0.1:3000, means "not set".

        The add-in picks a random port at every Revit start and publishes it in the registry, so a config
        that still pins :3000 (the old default in the DXT manifest, smithery and client configs) could
        never connect. Treating that exact value as unset lets discovery find the live Revit. Any other
        explicit URL stays pinned."""
        if isinstance(value, str):
            text = value.strip().rstrip("/").lower()
            if text in ("", "http://127.0.0.1:3000", "http://localhost:3000"):
                return None
        return value

    @field_validator("approval_mode", mode="before")
    def check_approval_mode(cls, value):
        return normalize_approval_mode(value)

    @field_validator("mcp_apps", mode="before")
    def check_mcp_apps(cls, value):
        return normalize_mcp_apps(value)

    @field_validator("approval_ttl", mode="before")
    def check_approval_ttl(cls, value):
        return normalize_ttl(value, APPROVAL_TTL_DEFAULT, "approval_ttl")

    @field_validator("pending_ttl", mode="before")
    def check_pending_ttl(cls, value):
        return normalize_ttl(value, PENDING_TTL_DEFAULT, "pending_ttl")

    @field_validator("allowed_directories", mode="before")
    def split_directories(cls, value, info):
        if isinstance(value, str):
            value = [Path(p.strip()) for p in value.split(";") if p.strip()]
        # The workspace itself is created on first use. Without this, a fresh install whose
        # workspace folder does not exist yet (for example ~/Documents when Documents is
        # redirected) made Config() fail on import and the hub died before it logged anything.
        # Any other allowed directory must already exist: the sandbox is never widened by guessing.
        workspace = info.data.get("workspace_dir")
        if workspace is not None and isinstance(value, list):
            for entry in value:
                if Path(entry) == Path(workspace):
                    try:
                        Path(entry).mkdir(parents=True, exist_ok=True)
                    except OSError:
                        pass  # DirectoryPath then reports the real problem
        return value

    @model_validator(mode="after")
    def _apply_defaults(self):
        auto: List[Path] = []
        if "workspace_dir" not in self.model_fields_set:
            auto.append(self.workspace_dir)
        if "allowed_directories" not in self.model_fields_set:
            # Sandbox stays closed: only the workspace itself is allowed.
            self.allowed_directories = [self.workspace_dir]
            if self.workspace_dir not in auto:
                auto.append(self.workspace_dir)
        else:
            # Every module reads/writes under allowed_directories[0], while the Revit
            # add-in writes snapshots under workspace_dir. Keep them the same directory
            # whenever the workspace is on the explicit allowed list (order only; the
            # sandbox is never widened).
            allowed = list(self.allowed_directories)
            for index, directory in enumerate(allowed):
                if index and directory.resolve() == self.workspace_dir.resolve():
                    allowed.insert(0, allowed.pop(index))
                    self.allowed_directories = allowed
                    break
        self._auto_dirs = auto
        return self

    def ensure_workspace(self) -> None:
        """Create the defaulted workspace directory if it does not exist yet.

        Only directories that came from defaults (the default workspace, or an
        allowed list derived from the workspace) are created; an explicitly
        configured allowed list is never created implicitly.
        """
        for directory in self._auto_dirs:
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        custom_env = _RawEnvSource(
            settings_cls,
            case_sensitive=env_settings.case_sensitive,
            env_prefix=env_settings.env_prefix,
            env_nested_delimiter=env_settings.env_nested_delimiter,
            env_nested_max_split=env_settings.env_nested_max_split,
            env_ignore_empty=env_settings.env_ignore_empty,
            env_parse_none_str=env_settings.env_parse_none_str,
            env_parse_enums=env_settings.env_parse_enums,
        )
        return init_settings, custom_env, dotenv_settings, file_secret_settings

    def workspace_allowed(self, path: Path) -> bool:
        path = path.resolve()
        return any(path.is_relative_to(allowed.resolve()) for allowed in self.allowed_directories)


config = Config()
