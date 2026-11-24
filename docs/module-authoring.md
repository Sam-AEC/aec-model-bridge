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

A manifest (and each command) may declare only these permission names. The list lives in `revit_mcp_server/security/module_permissions.py`; a test keeps this guide, the code and every built-in manifest in step.

- `model.read`: standard read tools.
- `model.write`: tools that change the model. The server always checks these against the action plan approval gate.
- `model.delete`: destructive operations.
- `params.write`: parameter value changes.
- `files.write`: writing files inside the sandboxed workspace.
- `net.local`: local connections.
- `net.cloud`: cloud sync.
- `python.host`: raw Python on the host, such as `revit_execute_python`. It stays off unless `allow_python_host` is `True`. Set this with `MCP_REVIT_ALLOW_PYTHON_HOST`.

An unknown name (a typo, or the old `workspace.write`, which is now `files.write`) logs a warning when the module loads. This is a warning for one release and will become a load error.

### What is enforced

- `python.host` is checked each time a command runs.
- `files.write`: the `workspace` argument a handler receives has `workspace.assert_writable(path)`. Call it on every path you are about to write. It does what `assert_in_workspace` does and also refuses with a `WorkspaceViolation` when neither the manifest nor the command declares `files.write`. `MCP_REVIT_MODULE_PERMISSION_MODE` is `enforce` (default) or `warn` (log and allow, for third-party modules that need time to declare the permission).
  Modules run in the server process, so this check covers handlers that use `assert_writable`; it is not a sandbox against code that calls `open()` directly.

## 3a. Importing other files from a module

The loader registers `module.py` in `sys.modules` as a plain module (`revit_mcp_server.modules.<id>`), not a package. A normal `from . import helper` or `import revit_mcp_server.modules.<id>.helper` fails, depending on load order. Load siblings by file path, for example with `importlib.util.spec_from_file_location(name, Path(__file__).parent / "helper.py")` and `module_from_spec`, and do not import another module's code.

## 4. Hooks

- **`validate` hook**: runs before the command. Return `{"ok": true}` to continue. Return `{"blockers": ["Details"]}` to stop the command.
- **`on_result` hook**: runs after the command, asynchronously.
