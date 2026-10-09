# Developer guide: module authoring

A module packages commands, workflows, schemas and QA rules. Developers and firms can add their own.

## 1. Directory structure

A module folder goes in one of these places:
- **Built-in**: `packages/mcp-server-revit/src/revit_mcp_server/modules/<module_id>/`
- **User or firm folder**: `%LOCALAPPDATA%\AECModelBridge\modules\<module_id>\`. The server loads it only when `enable_user_modules` is `True`. Set this with the environment variable `MCP_REVIT_ENABLE_USER_MODULES`.
- **Installed package**: the package declares an `aec_model_bridge.modules` entry point.

```
<module_id>/
├── module.json      # Manifest (required)
├── module.py        # Python commands & hooks (optional)
├── rules/           # QA/QC YAML rule definitions (optional)
└── ui/              # HTML panel components (optional)
```

## 2. Manifest schema (`module.json`)

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

The server checks the permissions in the manifest each time a command runs:
- `model.read`: standard read tools.
- `model.write`: tools that change the model. The server always checks these against the action plan approval gate.
- `model.delete`: destructive operations.
- `workspace.write`: writing files inside the sandboxed workspace.
- `net.local` and `net.cloud`: local connections and cloud sync.
- `python.host`: raw Python on the host, such as `revit_execute_python`. It stays off unless `allow_python_host` is `True`. Set this with `MCP_REVIT_ALLOW_PYTHON_HOST`.

## 4. Hooks

- **`validate` hook**: runs before the command. Return `{"ok": true}` to continue. Return `{"blockers": ["Details"]}` to stop the command.
- **`on_result` hook**: runs after the command, asynchronously.
