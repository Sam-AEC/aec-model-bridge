import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";
import {
  AUTO_APPROVAL_WARNING,
  BUNDLED_PYTHON,
  HealthResult,
  NOT_RUNNING_MESSAGE,
  buildEnv,
  interpretHealth,
  isRevitRegistryName,
  matchesRevitYear,
  newestFirst,
  normalizeSettings,
  parseRegistryFile,
  resolveWorkspaceDir,
  selectLaunch,
} from "./logic";

const PROVIDER_ID = "aecModelBridge.servers"; // must match contributes.mcpServerDefinitionProviders[].id
const INSTALL_GUIDE_URL = "https://github.com/Sam-AEC/aec-model-bridge/blob/main/docs/install.md";
const HEALTH_TIMEOUT_MS = 2000;

function readSettings() {
  const cfg = vscode.workspace.getConfiguration("aecModelBridge");
  return normalizeSettings({
    mode: cfg.get("mode"),
    revitYear: cfg.get("revitYear"),
    workspaceDir: cfg.get("workspaceDir"),
    approvalMode: cfg.get("approvalMode"),
  });
}

function registryDir(): string {
  const base = process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local");
  return path.join(base, "AECModelBridge", "registry");
}

/** Ask each running Revit (newest registry file first) for /health; first healthy answer wins. */
async function probeRevit(): Promise<HealthResult> {
  const year = readSettings().revitYear;
  let names: string[];
  try {
    names = fs.readdirSync(registryDir()).filter(isRevitRegistryName);
  } catch {
    return { connected: false, message: NOT_RUNNING_MESSAGE };
  }
  const files = newestFirst(
    names.flatMap((name) => {
      const full = path.join(registryDir(), name);
      try {
        return [{ full, mtimeMs: fs.statSync(full).mtimeMs }];
      } catch {
        return [];
      }
    }),
  );
  let lastError = NOT_RUNNING_MESSAGE;
  for (const file of files) {
    let entry;
    try {
      entry = parseRegistryFile(fs.readFileSync(file.full, "utf8"));
    } catch {
      continue;
    }
    if (!entry || !matchesRevitYear(entry.hostVersion, year)) continue;
    try {
      const res = await fetch(`${entry.endpoint}/health`, { signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS) });
      if (!res.ok) {
        lastError = `Revit answered with HTTP ${res.status}.`;
        continue;
      }
      const result = interpretHealth(await res.json(), entry.hostVersion);
      if (result.connected) return result;
      lastError = result.message;
    } catch {
      lastError = "Found a Revit session file, but Revit did not answer. It may have closed; restart Revit and try again.";
    }
  }
  return { connected: false, message: lastError };
}

export function activate(context: vscode.ExtensionContext): void {
  const changed = new vscode.EventEmitter<void>();
  const version: string = context.extension.packageJSON.version;

  // --- MCP server definition provider ---------------------------------------
  const provider: vscode.McpServerDefinitionProvider<vscode.McpStdioServerDefinition> = {
    onDidChangeMcpServerDefinitions: changed.event,
    provideMcpServerDefinitions() {
      const settings = readSettings();
      const launch = selectLaunch(fs.existsSync(BUNDLED_PYTHON));
      const workspaceDir = resolveWorkspaceDir(
        settings.workspaceDir,
        vscode.workspace.workspaceFolders?.find((folder) => folder.uri.scheme === "file")?.uri.fsPath,
        os.homedir(),
      );
      return [
        new vscode.McpStdioServerDefinition(
          "AEC Model Bridge",
          launch.command,
          launch.args,
          buildEnv(settings, workspaceDir),
          version,
        ),
      ];
    },
    async resolveMcpServerDefinition(server) {
      // Called right before the server starts, so user interaction is allowed here.
      if (server.env.MCP_REVIT_APPROVAL_MODE === "auto") {
        const choice = await vscode.window.showWarningMessage(
          AUTO_APPROVAL_WARNING,
          { modal: true },
          "Start anyway",
          "Switch back to required",
        );
        if (choice === "Switch back to required") {
          await updateSetting("approvalMode", "required");
          return undefined;
        }
        if (choice !== "Start anyway") return undefined;
      }
      return server;
    },
  };
  context.subscriptions.push(vscode.lm.registerMcpServerDefinitionProvider(PROVIDER_ID, provider), changed);

  // --- Status bar --------------------------------------------------------------
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.command = "aecModelBridge.checkConnection";
  context.subscriptions.push(status);

  const refresh = async (): Promise<HealthResult | undefined> => {
    if (readSettings().mode === "mock") {
      status.text = "$(beaker) AEC: mock mode";
      status.tooltip = "AEC Model Bridge is using simulated data. Click to check the Revit connection.";
      status.show();
      return undefined;
    }
    const result = await probeRevit();
    status.text = result.connected
      ? `$(check) AEC: Connected${result.revitYear ? ` (Revit ${result.revitYear})` : ""}`
      : "$(circle-slash) AEC: Not connected";
    status.tooltip = result.message;
    status.show();
    return result;
  };

  let timer: NodeJS.Timeout | undefined;
  const schedule = () => {
    if (timer) clearInterval(timer);
    const seconds = vscode.workspace.getConfiguration("aecModelBridge").get<number>("statusRefreshSeconds", 30);
    timer = setInterval(() => void refresh(), Math.min(600, Math.max(5, seconds)) * 1000);
  };
  context.subscriptions.push({ dispose: () => timer && clearInterval(timer) });
  void refresh();
  schedule();

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("aecModelBridge")) {
        changed.fire(); // tell VS Code to re-read the server definition
        schedule();
        void refresh();
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => changed.fire()),
  );

  // --- Commands ----------------------------------------------------------------
  context.subscriptions.push(
    vscode.commands.registerCommand("aecModelBridge.checkConnection", async () => {
      const result = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Window, title: "AEC Model Bridge: checking Revit" },
        () => refresh(),
      );
      if (!result) {
        void vscode.window.showInformationMessage(
          "AEC Model Bridge is in mock mode, so it does not need Revit. Switch the aecModelBridge.mode setting to bridge to use a live Revit.",
        );
      } else if (result.connected) {
        void vscode.window.showInformationMessage(result.message);
      } else {
        const pick = await vscode.window.showWarningMessage(result.message, "Open install guide", "Use mock mode");
        if (pick === "Open install guide") await vscode.commands.executeCommand("aecModelBridge.openInstallGuide");
        if (pick === "Use mock mode") await vscode.commands.executeCommand("aecModelBridge.useMockMode");
      }
    }),
    vscode.commands.registerCommand("aecModelBridge.openInstallGuide", () =>
      vscode.env.openExternal(vscode.Uri.parse(INSTALL_GUIDE_URL)),
    ),
    vscode.commands.registerCommand("aecModelBridge.useMockMode", async () => {
      await updateSetting("mode", "mock");
      void vscode.window.showInformationMessage(
        "AEC Model Bridge now uses mock mode (simulated data, no Revit needed). Restart the server from the MCP: List Servers command if it is already running.",
      );
    }),
  );
}

export function deactivate(): void {}

/** Write at the scope supplying the effective value so workspace overrides are changed too. */
async function updateSetting(name: string, value: string): Promise<void> {
  const cfg = vscode.workspace.getConfiguration("aecModelBridge");
  const inspected = cfg.inspect(name);
  const target = inspected?.workspaceFolderValue !== undefined
    ? vscode.ConfigurationTarget.WorkspaceFolder
    : inspected?.workspaceValue !== undefined
      ? vscode.ConfigurationTarget.Workspace
      : vscode.ConfigurationTarget.Global;
  await cfg.update(name, value, target);
}
