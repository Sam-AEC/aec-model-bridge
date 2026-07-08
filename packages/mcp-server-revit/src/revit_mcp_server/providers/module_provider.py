from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.module_registry import ModuleRegistry, ModuleInstance, CommandSpec
from revit_mcp_server.security.workspace import WorkspaceMonitor
from .base import AECProvider, ProviderTool

logger = logging.getLogger(__name__)

def validate_json_schema(data: Any, schema: Dict[str, Any], path: str = "root") -> None:
    if not schema:
        return
    
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(data, dict):
            raise ValueError(f"Value at {path} must be an object/dict")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for req in required:
            if req not in data:
                prop_schema = properties.get(req, {})
                if "default" not in prop_schema:
                    raise ValueError(f"Missing required field '{req}' at {path}")
                else:
                    data[req] = prop_schema["default"]
        
        for k, v in data.items():
            if k in properties:
                validate_json_schema(v, properties[k], f"{path}.{k}")
                
    elif schema_type == "array":
        if not isinstance(data, list):
            raise ValueError(f"Value at {path} must be a list/array")
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(data):
                validate_json_schema(item, items_schema, f"{path}[{idx}]")
                
    elif schema_type == "string":
        if not isinstance(data, str):
            raise ValueError(f"Value at {path} must be a string")
            
    elif schema_type == "integer":
        if not isinstance(data, int) or isinstance(data, bool):
            raise ValueError(f"Value at {path} must be an integer")
            
    elif schema_type == "number":
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            raise ValueError(f"Value at {path} must be a number")
            
    elif schema_type == "boolean":
        if not isinstance(data, bool):
            raise ValueError(f"Value at {path} must be a boolean")

class ModuleProvider(AECProvider):
    def __init__(self, module_registry: ModuleRegistry, workspace: WorkspaceMonitor):
        self.registry = module_registry
        self.workspace = workspace

    def get_identity(self) -> str:
        return "module"

    def get_capabilities(self) -> List[ProviderTool]:
        tools = []
        # Expose the listing tool for panels
        tools.append(ProviderTool(
            name="module_list_commands",
            description="List all registered modules and their commands for dockable panels",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ))
        
        for m in self.registry.get_all_modules():
            for cmd in m.manifest.commands:
                # Carry over all metadata
                tools.append(ProviderTool(
                    name=f"{m.manifest.id}_{cmd.id}",
                    description=cmd.title,
                    inputSchema=cmd.input_schema or {"type": "object", "properties": {}, "required": []},
                    is_mutating=cmd.is_mutating,
                    destructive=cmd.destructive,
                    execution_mode=cmd.execution_mode,
                    permissions=cmd.permissions
                ))
        return tools

    async def check_health(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "loaded_modules_count": len(self.registry.get_all_modules())
        }

    async def shutdown(self) -> None:
        pass

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "module_list_commands":
            return self._list_commands()
            
        # Resolve target module and command
        module_inst: Optional[ModuleInstance] = None
        command_spec: Optional[CommandSpec] = None
        
        for m in self.registry.get_all_modules():
            for cmd in m.manifest.commands:
                if f"{m.manifest.id}_{cmd.id}" == name:
                    module_inst = m
                    command_spec = cmd
                    break
            if module_inst:
                break
                
        if not module_inst or not command_spec:
            raise BridgeError(f"Module tool '{name}' not found in registry")
            
        # 1. Enforce permissions
        required_perms = command_spec.permissions + module_inst.manifest.permissions
        if "python.host" in required_perms:
            if not getattr(self.registry.config, "allow_python_host", False):
                raise BridgeError(
                    f"Permission 'python.host' is required by command '{name}' but disabled in configuration."
                )
                
        # 2. Schema Input validation
        if command_spec.input_schema:
            try:
                validate_json_schema(arguments, command_spec.input_schema)
            except Exception as e:
                raise BridgeError(f"Input schema validation failed: {e}")
                
        # 3. Validate hook execution
        validate_fn = module_inst.get_hook_callable("validate")
        if validate_fn:
            try:
                val_res = await self._run_callable_with_timeout(validate_fn, arguments, timeout=2.0)
                if isinstance(val_res, dict):
                    blockers = val_res.get("blockers")
                    if blockers:
                        raise BridgeError(f"Validation hook blocked execution: {blockers}")
            except BridgeError:
                raise
            except Exception as e:
                logger.warning(f"Error running validate hook for '{name}': {e}")
                
        # 4. Command execution
        cmd_fn = None
        if module_inst.class_instance:
            cmd_fn = getattr(module_inst.class_instance, command_spec.id, None)
        elif module_inst.code_module:
            cmd_fn = getattr(module_inst.code_module, command_spec.id, None)
            
        if not cmd_fn:
            raise BridgeError(f"Implementation for command '{command_spec.id}' not found in module code")
            
        # Run execution
        try:
            result = await self._run_callable(cmd_fn, arguments)
        except Exception as e:
            raise BridgeError(f"Command execution failed: {e}") from e
            
        # 5. Schema Output validation
        if command_spec.output_schema and isinstance(result, dict):
            try:
                validate_json_schema(result, command_spec.output_schema)
            except Exception as e:
                logger.warning(f"Output schema validation failed: {e}")
                
        # 6. on_result hook execution
        result_fn = module_inst.get_hook_callable("on_result")
        if result_fn:
            try:
                # Run hook in the background safely
                asyncio.create_task(
                    self._run_callable_with_timeout(result_fn, {"arguments": arguments, "result": result}, timeout=2.0)
                )
            except Exception as e:
                logger.warning(f"Error queuing on_result hook: {e}")
                
        return result

    def _list_commands(self) -> Dict[str, Any]:
        module_list = []
        for m in self.registry.get_all_modules():
            cmd_list = []
            for cmd in m.manifest.commands:
                cmd_list.append({
                    "id": cmd.id,
                    "title": cmd.title,
                    "surface": cmd.surface,
                    "execution_mode": cmd.execution_mode,
                    "is_mutating": cmd.is_mutating,
                    "destructive": cmd.destructive,
                    "requires_plan": cmd.requires_plan
                })
            module_list.append({
                "id": m.manifest.id,
                "name": m.manifest.name,
                "version": m.manifest.version,
                "description": getattr(m.manifest, "description", ""),
                "commands": cmd_list,
                "ui": m.manifest.ui
            })
        return {"modules": module_list}

    async def _run_callable(self, func: Callable[..., Any], arguments: Dict[str, Any]) -> Any:
        sig = inspect.signature(func)
        kwargs = {}
        for param_name, param in sig.parameters.items():
            if param_name in ("payload", "arguments"):
                kwargs[param_name] = arguments
            elif param_name == "workspace":
                kwargs[param_name] = self.workspace
            elif param_name in arguments:
                kwargs[param_name] = arguments[param_name]
                
        if not kwargs and len(sig.parameters) > 0:
            if inspect.iscoroutinefunction(func):
                return await func(arguments)
            else:
                return await asyncio.get_running_loop().run_in_executor(None, func, arguments)
                
        if inspect.iscoroutinefunction(func):
            return await func(**kwargs)
        else:
            return await asyncio.get_running_loop().run_in_executor(None, lambda: func(**kwargs))

    async def _run_callable_with_timeout(self, func: Callable[..., Any], *args, timeout: float = 2.0) -> Any:
        try:
            return await asyncio.wait_for(self._run_callable(func, *args), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout budget exceeded during hook execution ({timeout}s)")
            return None
