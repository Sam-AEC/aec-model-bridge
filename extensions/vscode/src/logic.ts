// Pure logic: no "vscode" import, so it can be unit tested with plain Node.
import * as path from "node:path";

export const BUNDLED_PYTHON = "C:\\ProgramData\\AECModelBridge\\python\\python.exe";
export const UVX_SOURCE =
  "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit";

export type Mode = "bridge" | "mock";
export type ApprovalMode = "required" | "auto";
export type RevitYear = "auto" | "2024" | "2025" | "2026" | "2027";

export interface Settings {
  mode: Mode;
  revitYear: RevitYear;
  workspaceDir: string;
  approvalMode: ApprovalMode;
}

export interface Launch {
  command: string;
  args: string[];
  kind: "bundled" | "uvx";
}

/** Prefer the python bundled by the installer; fall back to uvx. */
export function selectLaunch(bundledPythonExists: boolean, bundledPython = BUNDLED_PYTHON): Launch {
  if (bundledPythonExists) {
    return { command: bundledPython, args: ["-m", "revit_mcp_server.mcp_server"], kind: "bundled" };
  }
  return { command: "uvx", args: ["--from", UVX_SOURCE, "aec-model-bridge"], kind: "uvx" };
}

/** Normalise raw configuration values, falling back to safe defaults. */
export function normalizeSettings(raw: Partial<Record<keyof Settings, unknown>>): Settings {
  const years = ["auto", "2024", "2025", "2026", "2027"];
  return {
    mode: raw.mode === "mock" ? "mock" : "bridge",
    revitYear: years.includes(String(raw.revitYear)) ? (String(raw.revitYear) as RevitYear) : "auto",
    workspaceDir: typeof raw.workspaceDir === "string" ? raw.workspaceDir.trim() : "",
    // Anything other than an explicit "auto" keeps the approval gate on.
    approvalMode: raw.approvalMode === "auto" ? "auto" : "required",
  };
}

/** Configured folder, else the first folder open in VS Code, else Documents. */
export function resolveWorkspaceDir(configured: string, firstFolder: string | undefined, home: string): string {
  if (configured) return configured;
  if (firstFolder) return firstFolder;
  return path.win32.join(home, "Documents");
}

/** Settings to the environment variables the server reads (prefix MCP_REVIT_). */
export function buildEnv(settings: Settings, workspaceDir: string): Record<string, string | null> {
  const env: Record<string, string | null> = {
    MCP_REVIT_MODE: settings.mode,
    MCP_REVIT_WORKSPACE_DIR: workspaceDir,
    MCP_REVIT_ALLOWED_DIRECTORIES: JSON.stringify([workspaceDir]),
    MCP_REVIT_APPROVAL_MODE: settings.approvalMode,
    MCP_REVIT_HOST_VERSION: settings.revitYear === "auto" ? null : settings.revitYear,
    MCP_REVIT_BRIDGE_URL: null,
  };
  return env;
}

/** Match the server's year selection, including full version strings such as 2026.1. */
export function matchesRevitYear(hostVersion: string | undefined, year: RevitYear): boolean {
  return year === "auto" || !!hostVersion?.startsWith(year);
}

export interface RegistryEntry {
  endpoint: string;
  hostVersion?: string;
  pid?: number;
  startedAt?: string;
}

/** Parse one registry/revit-*.json file. Returns undefined when unusable. */
export function parseRegistryFile(text: string): RegistryEntry | undefined {
  let data: unknown;
  try {
    data = JSON.parse(text.replace(/^\uFEFF/, ""));
  } catch {
    return undefined;
  }
  if (typeof data !== "object" || data === null) return undefined;
  const d = data as Record<string, unknown>;
  if (typeof d.endpoint !== "string" || !/^https?:\/\//i.test(d.endpoint)) return undefined;
  return {
    endpoint: d.endpoint.replace(/\/+$/, ""),
    hostVersion: d.host_version !== undefined ? String(d.host_version) : undefined,
    pid: typeof d.pid === "number" ? d.pid : undefined,
    startedAt: typeof d.started_at === "string" ? d.started_at : undefined,
  };
}

/** Only revit-*.json files count. */
export function isRevitRegistryName(name: string): boolean {
  return /^revit-.*\.json$/i.test(name);
}

/** Newest file first by modification time. */
export function newestFirst<T extends { mtimeMs: number }>(files: T[]): T[] {
  return [...files].sort((a, b) => b.mtimeMs - a.mtimeMs);
}

export interface HealthResult {
  connected: boolean;
  revitYear?: string;
  message: string;
}

/** Turn a /health JSON body into a result. */
export function interpretHealth(body: unknown, fallbackYear?: string): HealthResult {
  const b = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  if (b.status === "healthy") {
    const year = b.revit_version !== undefined ? String(b.revit_version) : fallbackYear;
    return { connected: true, revitYear: year, message: year ? `Connected to Revit ${year}` : "Connected to Revit" };
  }
  return { connected: false, message: `Revit answered but is not healthy (status: ${String(b.status ?? "unknown")}).` };
}

export const NOT_RUNNING_MESSAGE =
  "No running Revit found. Start Revit with the AEC Model Bridge add-in installed, or switch to mock mode.";

export const AUTO_APPROVAL_WARNING =
  "Approval mode is set to auto. The AI agent can change or delete things in your Revit model without asking first. Only continue if you accept that risk.";
