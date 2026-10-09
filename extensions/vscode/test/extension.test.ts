import { build } from "esbuild";
import { createRequire } from "node:module";
import * as path from "node:path";
import * as vm from "node:vm";
import { beforeAll, describe, expect, it, vi } from "vitest";

let extensionCode: string;
beforeAll(async () => {
  const result = await build({ entryPoints: ["src/extension.ts"], bundle: true, platform: "node", format: "cjs", external: ["vscode"], write: false });
  extensionCode = result.outputFiles[0].text;
});

function activate(settings: Record<string, unknown> = {}, workspaceValues: Record<string, unknown> = {}, scheme = "file") {
  let provider: any;
  const commands = new Map<string, (...args: any[]) => any>();
  const subscriptions: { dispose(): void }[] = [];
  const warning = vi.fn().mockResolvedValue(undefined);
  const updates: { name: string; value: unknown; target: number }[] = [];
  const config = {
    get: (name: string, fallback: unknown) => workspaceValues[name] ?? settings[name] ?? fallback,
    inspect: (name: string) => ({ workspaceValue: workspaceValues[name] }),
    update: vi.fn(async (name: string, value: unknown, target: number) => {
      updates.push({ name, value, target });
      (target === 2 ? workspaceValues : settings)[name] = value;
    }),
  };
  const disposable = () => ({ dispose() {} });
  const vscode = {
    EventEmitter: class { event = () => disposable(); fire() {} dispose() {} },
    McpStdioServerDefinition: class {
      constructor(public label: string, public command: string, public args: string[], public env: Record<string, string | null>, public version: string) {}
    },
    lm: { registerMcpServerDefinitionProvider: (_: string, p: unknown) => { provider = p; return disposable(); } },
    workspace: { getConfiguration: () => config, workspaceFolders: [{ uri: { scheme, fsPath: "C:\\project" } }], onDidChangeConfiguration: disposable, onDidChangeWorkspaceFolders: disposable },
    window: { createStatusBarItem: () => ({ show() {}, dispose() {} }), showWarningMessage: warning, showInformationMessage: vi.fn() },
    commands: { registerCommand: (name: string, action: (...args: any[]) => any) => { commands.set(name, action); return disposable(); } },
    ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
    StatusBarAlignment: { Left: 1 },
  };
  const require = createRequire(path.resolve("package.json"));
  const module: { exports: any } = { exports: {} };
  vm.runInNewContext(extensionCode, {
    exports: module.exports, module, require: (id: string) => id === "vscode" ? vscode : require(id),
    process, setInterval: () => 1, clearInterval() {},
  });
  // Mock mode keeps startup probing independent of any live Revit session.
  module.exports.activate({ subscriptions, extension: { packageJSON: { version: "1.3.3" } } });
  return { provider, commands, warning, updates, settings, subscriptions };
}

describe("extension start and settings", () => {
  it("asks for approval based on the definition that will actually start", async () => {
    const fixture = activate({ mode: "mock", approvalMode: "auto" });
    const server = fixture.provider.provideMcpServerDefinitions()[0];
    fixture.settings.approvalMode = "required";
    await expect(fixture.provider.resolveMcpServerDefinition(server)).resolves.toBeUndefined();
    expect(fixture.warning).toHaveBeenCalledOnce();
  });
  it("changes a workspace auto override back to required", async () => {
    const fixture = activate({ mode: "mock" }, { approvalMode: "auto" });
    fixture.warning.mockResolvedValue("Switch back to required");
    const server = fixture.provider.provideMcpServerDefinitions()[0];
    await fixture.provider.resolveMcpServerDefinition(server);
    expect(fixture.updates).toEqual([{ name: "approvalMode", value: "required", target: 2 }]);
    expect(fixture.provider.provideMcpServerDefinitions()[0].env.MCP_REVIT_APPROVAL_MODE).toBe("required");
  });
  it("changes the mode at the scope that supplied it", async () => {
    const fixture = activate({ mode: "mock" }, { mode: "mock" });
    await fixture.commands.get("aecModelBridge.useMockMode")!();
    expect(fixture.updates).toEqual([{ name: "mode", value: "mock", target: 2 }]);
  });
  it("does not pass a remote workspace path to a local Windows server", () => {
    const fixture = activate({ mode: "mock" }, {}, "vscode-remote");
    const server = fixture.provider.provideMcpServerDefinitions()[0];
    expect(server.env.MCP_REVIT_WORKSPACE_DIR).not.toBe("C:\\project");
    expect(server.env.MCP_REVIT_WORKSPACE_DIR).toMatch(/Documents$/);
  });
});
