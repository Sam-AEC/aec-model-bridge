from __future__ import annotations

import json
import logging
import os
import sys
import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

class CommandSpec(BaseModel):
    id: str
    title: str
    surface: List[str] = Field(default_factory=lambda: ["mcp"])
    mcp_tool: Optional[str] = None
    execution_mode: str = "sync"  # "sync" | "async"
    is_mutating: bool = False
    destructive: bool = False
    requires_plan: bool = False
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    permissions: List[str] = Field(default_factory=list)

class ModuleManifest(BaseModel):
    id: str
    name: str
    version: str
    schema_version: int = 1
    min_hub_version: str = "1.2.0"
    requires_providers: List[str] = Field(default_factory=list)
    requires_tools: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    commands: List[CommandSpec] = Field(default_factory=list)
    ui: Optional[Dict[str, Any]] = None
    hooks: Optional[Dict[str, str]] = None

class ModuleInstance:
    def __init__(self, manifest: ModuleManifest, directory: Path):
        self.manifest = manifest
        self.directory = directory
        self.code_module = None
        self.class_instance = None
        
        py_path = directory / "module.py"
        if py_path.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"revit_mcp_server.modules.{manifest.id}", py_path
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[f"revit_mcp_server.modules.{manifest.id}"] = mod
                    spec.loader.exec_module(mod)
                    self.code_module = mod
                    
                    # Instantiate singleton class instance if dynamic class hook pattern is used
                    cls_name = "".join(x.capitalize() for x in manifest.id.split("_")) + "Module"
                    cls = getattr(mod, cls_name, None)
                    if cls and isinstance(cls, type):
                        self.class_instance = cls()
            except Exception as e:
                logger.error(f"Failed to load Python code for module '{manifest.id}': {e}")

    def get_hook_callable(self, hook_name: str) -> Optional[Callable[..., Any]]:
        if not self.manifest.hooks:
            return None
        hook_str = self.manifest.hooks.get(hook_name)
        if not hook_str or not hook_str.startswith("module:"):
            return None
        
        path = hook_str[len("module:"):]
        parts = path.split(".")
        
        # Resolve from code module
        if not self.code_module:
            return None
            
        if len(parts) == 1:
            # Simple function at module level
            return getattr(self.code_module, parts[0], None)
        elif len(parts) == 2:
            # Class method/instance method
            cls_name, method_name = parts
            if self.class_instance and self.class_instance.__class__.__name__ == cls_name:
                return getattr(self.class_instance, method_name, None)
            
            # Fallback check if the class exists on code_module
            cls = getattr(self.code_module, cls_name, None)
            if cls and isinstance(cls, type):
                if not self.class_instance or not isinstance(self.class_instance, cls):
                    try:
                        self.class_instance = cls()
                    except Exception as e:
                        logger.error(f"Failed to instantiate hook class {cls_name}: {e}")
                        return None
                return getattr(self.class_instance, method_name, None)
                
        return None

class ModuleRegistry:
    def __init__(self, config_obj: Any = None):
        self.config = config_obj
        self.modules: Dict[str, ModuleInstance] = {}

    def discover_and_load(self) -> None:
        self.modules.clear()
        
        # 1. Load built-in modules
        built_in_dir = Path(__file__).parent / "modules"
        if built_in_dir.exists() and built_in_dir.is_dir():
            for child in built_in_dir.iterdir():
                if child.is_dir() and (child / "module.json").exists():
                    self._load_module_dir(child, "built-in")
                    
        # 2. Load Entry Points
        try:
            # Python 3.10+ entry points API
            import importlib.metadata
            eps = importlib.metadata.entry_points(group="aec_model_bridge.modules")
            for ep in eps:
                try:
                    # An entry point can return a path string or a module path
                    module_path = ep.load()
                    if isinstance(module_path, str):
                        path = Path(module_path)
                    elif hasattr(module_path, "__file__") and module_path.__file__:
                        path = Path(module_path.__file__).parent
                    else:
                        continue
                    if path.exists() and (path / "module.json").exists():
                        self._load_module_dir(path, "entry-point")
                except Exception as e:
                    logger.error(f"Failed to load module entry point '{ep.name}': {e}")
        except Exception as e:
            logger.warning(f"Error resolving entry points: {e}")

        # 3. Load User modules if enabled
        enable_user = getattr(self.config, "enable_user_modules", False)
        if enable_user:
            local_app_data = os.getenv("LOCALAPPDATA")
            if local_app_data:
                user_modules_dir = Path(local_app_data) / "AECModelBridge" / "modules"
            else:
                user_modules_dir = Path.home() / "AppData" / "Local" / "AECModelBridge" / "modules"
                
            if user_modules_dir.exists() and user_modules_dir.is_dir():
                for child in user_modules_dir.iterdir():
                    if child.is_dir() and (child / "module.json").exists():
                        self._load_module_dir(child, "user")
        else:
            logger.info("User modules directory scanning is disabled in configuration.")

    def _load_module_dir(self, directory: Path, source_type: str) -> None:
        manifest_path = directory / "module.json"
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            manifest = ModuleManifest(**data)
            
            # Version checks: min_hub_version gate
            hub_version = "1.2.0"
            if manifest.min_hub_version:
                # Basic check: compare major/minor parts
                try:
                    h_parts = [int(x) for x in hub_version.split(".")]
                    m_parts = [int(x) for x in manifest.min_hub_version.split(".")]
                    if m_parts > h_parts:
                        logger.warning(
                            f"Skipping module '{manifest.id}': requires hub version {manifest.min_hub_version} but running {hub_version}"
                        )
                        return
                except ValueError:
                    # Ignore invalid semver parsing and skip safety checks if format is weird
                    pass
            
            # Collision handling
            if manifest.id in self.modules:
                logger.warning(
                    f"Collision detected: module ID '{manifest.id}' from {source_type} directory '{directory}' "
                    f"overrides previously loaded module from '{self.modules[manifest.id].directory}'"
                )
                
            # Create instance and add
            self.modules[manifest.id] = ModuleInstance(manifest, directory)
            logger.info(f"Loaded module '{manifest.id}' from {directory} ({source_type})")
            
        except Exception as e:
            logger.error(f"Failed to load module manifest from '{manifest_path}': {e}")

    def get_module(self, module_id: str) -> Optional[ModuleInstance]:
        return self.modules.get(module_id)

    def get_all_modules(self) -> List[ModuleInstance]:
        return list(self.modules.values())
