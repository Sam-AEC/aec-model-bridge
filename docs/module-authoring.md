# Developer Guide: Module Authoring

Modules in AEC Model Bridge allow developers and firms to package commands, workflows, schemas, and QA rules.

## 1. Directory Structure

A module folder must reside either:
- **Built-in**: `packages/mcp-server-revit/src/revit_mcp_server/modules/<module_id>/`
- **User/Firm Folder** (if `enable_user_modules` is `True`): `%LOCALAPPDATA%\AECModelBridge\modules\<module_id>\`
- **Installed Package**: Declared as `aec_model_bridge.modules` entry points.

```
<module_id>/
├── module.json      # Manifest (required)
├── module.py        # Python commands & hooks (optional)
├── rules/           # QA/QC YAML rule definitions (optional)
└── ui/              # HTML panel components (optional)
```

## 2. Manifest Schema (`module.json`)

```json
{
  "id": "hello_world",
  "name": "Hello World Module",
  "version": "1.0.0",
  "schema_version": 1,
  "min_hub_version": "1.2.0",
  "description": "A demo module.",
  "author": "AEC Model Bridge",
  "license": "GPL-3.0-or-later",
  "requires_providers": ["revit"],
  "permissions": ["model.read"],
  "commands": [
    {
      "id": "say_hello",
      "title": "Say Hello",
      "surface": ["mcp"],
      "execution_mode": "sync",
      "is_mutating": false,
      "input_schema": {
        "type": "object",
        "properties": {
          "name": {"type": "string", "default": "World"}
        },
        "required": ["name"]
      }
    }
  ],
  "hooks": {
    "validate": "module:HelloWorldModule.validate",
    "on_result": "module:HelloWorldModule.on_result"
  }
}
```

## 3. Permissions

Permissions declared in the manifest are verified at dispatch time:
- `model.read`: Standard read tools.
- `model.write`: Mutating tools (always checked against the ActionPlan approval gate).
- `model.delete`: Destructive operations.
- `workspace.write`: Restricted sandboxed files output.
- `net.local` / `net.cloud`: Local connection vs cloud synchronizations.
- `python.host`: Raw python escapes (e.g. `revit_execute_python`). Disabled unless `allow_python_host` is explicitly `True`.

## 4. Hook Evaluation

- **`validate` hook**: Called before execution. Returns `{"ok": true}` or `{"blockers": ["Details"]}` to reject execution.
- **`on_result` hook**: Called after execution asynchronously.
