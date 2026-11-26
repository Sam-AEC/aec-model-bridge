import { describe, expect, it } from "vitest";
import {
  BUNDLED_PYTHON,
  UVX_SOURCE,
  buildEnv,
  interpretHealth,
  isRevitRegistryName,
  matchesRevitYear,
  newestFirst,
  normalizeSettings,
  parseRegistryFile,
  resolveWorkspaceDir,
  selectLaunch,
} from "../src/logic";

describe("selectLaunch", () => {
  it("prefers the bundled python", () => {
    expect(selectLaunch(true)).toEqual({
      command: BUNDLED_PYTHON,
      args: ["-m", "revit_mcp_server.mcp_server"],
      kind: "bundled",
    });
  });
  it("falls back to uvx from the git subdirectory", () => {
    const l = selectLaunch(false);
    expect(l.command).toBe("uvx");
    expect(l.args).toEqual(["--from", UVX_SOURCE, "aec-model-bridge"]);
    expect(UVX_SOURCE).toContain("#subdirectory=packages/mcp-server-revit");
  });
});

describe("normalizeSettings", () => {
  it("defaults to bridge, auto year, approvals required", () => {
    expect(normalizeSettings({})).toEqual({ mode: "bridge", revitYear: "auto", workspaceDir: "", approvalMode: "required" });
  });
  it("rejects unknown values and keeps the approval gate on", () => {
    const s = normalizeSettings({ mode: "x", revitYear: "1999", approvalMode: "off", workspaceDir: 5 });
    expect(s).toEqual({ mode: "bridge", revitYear: "auto", workspaceDir: "", approvalMode: "required" });
  });
  it("accepts explicit values", () => {
    const s = normalizeSettings({ mode: "mock", revitYear: "2026", approvalMode: "auto", workspaceDir: " C:\\p " });
    expect(s).toEqual({ mode: "mock", revitYear: "2026", workspaceDir: "C:\\p", approvalMode: "auto" });
  });
});

describe("resolveWorkspaceDir", () => {
  it("uses configured, then first folder, then Documents", () => {
    expect(resolveWorkspaceDir("C:\\a", "C:\\b", "C:\\Users\\u")).toBe("C:\\a");
    expect(resolveWorkspaceDir("", "C:\\b", "C:\\Users\\u")).toBe("C:\\b");
    expect(resolveWorkspaceDir("", undefined, "C:\\Users\\u")).toBe("C:\\Users\\u\\Documents");
  });
});

describe("buildEnv", () => {
  it("maps settings to MCP_REVIT_* variables", () => {
    const env = buildEnv(normalizeSettings({ mode: "mock", revitYear: "2025", approvalMode: "auto" }), "C:\\w");
    expect(env).toEqual({
      MCP_REVIT_MODE: "mock",
      MCP_REVIT_WORKSPACE_DIR: "C:\\w",
      MCP_REVIT_ALLOWED_DIRECTORIES: JSON.stringify(["C:\\w"]),
      MCP_REVIT_APPROVAL_MODE: "auto",
      MCP_REVIT_HOST_VERSION: "2025",
      MCP_REVIT_BRIDGE_URL: null,
    });
  });
  it("clears inherited connection overrides on auto", () => {
    const env = buildEnv(normalizeSettings({}), "C:\\w");
    expect(env.MCP_REVIT_HOST_VERSION).toBeNull();
    expect(env.MCP_REVIT_BRIDGE_URL).toBeNull();
    expect(env.MCP_REVIT_MODE).toBe("bridge");
    expect(env.MCP_REVIT_APPROVAL_MODE).toBe("required");
  });
  it("preserves a folder containing a semicolon as one allowed directory", () => {
    const folder = "C:\\exports;reports";
    expect(JSON.parse(buildEnv(normalizeSettings({}), folder).MCP_REVIT_ALLOWED_DIRECTORIES!)).toEqual([folder]);
  });
});

describe("matchesRevitYear", () => {
  it("limits the status probe to the same year as the MCP server", () => {
    expect(matchesRevitYear("2026.1", "2026")).toBe(true);
    expect(matchesRevitYear("2025", "2026")).toBe(false);
    expect(matchesRevitYear(undefined, "2026")).toBe(false);
    expect(matchesRevitYear("2025", "auto")).toBe(true);
  });
});

describe("parseRegistryFile", () => {
  const good = JSON.stringify({
    provider_id: "revit-2026",
    endpoint: "http://127.0.0.1:3000/",
    pid: 42,
    host_version: "2026",
    started_at: "2026-10-09T10:00:00Z",
  });
  it("reads endpoint and metadata, trimming the trailing slash", () => {
    expect(parseRegistryFile(good)).toEqual({
      endpoint: "http://127.0.0.1:3000",
      hostVersion: "2026",
      pid: 42,
      startedAt: "2026-10-09T10:00:00Z",
    });
  });
  it("tolerates a UTF-8 BOM", () => {
    expect(parseRegistryFile("\uFEFF" + good)?.endpoint).toBe("http://127.0.0.1:3000");
  });
  it("rejects bad json, missing or non-http endpoints", () => {
    expect(parseRegistryFile("{nope")).toBeUndefined();
    expect(parseRegistryFile("[]")).toBeUndefined();
    expect(parseRegistryFile("{}")).toBeUndefined();
    expect(parseRegistryFile(JSON.stringify({ endpoint: "file:///x" }))).toBeUndefined();
  });
});

describe("registry file selection", () => {
  it("matches only revit-*.json", () => {
    expect(isRevitRegistryName("revit-2026.json")).toBe(true);
    expect(isRevitRegistryName("rhino-8.json")).toBe(false);
    expect(isRevitRegistryName("revit-2026.json.tmp")).toBe(false);
  });
  it("orders newest first without mutating the input", () => {
    const input = [{ n: "a", mtimeMs: 1 }, { n: "b", mtimeMs: 3 }, { n: "c", mtimeMs: 2 }];
    expect(newestFirst(input).map((f) => f.n)).toEqual(["b", "c", "a"]);
    expect(input[0].n).toBe("a");
  });
});

describe("interpretHealth", () => {
  it("reports the Revit year when healthy", () => {
    expect(interpretHealth({ status: "healthy", revit_version: "2026" })).toMatchObject({ connected: true, revitYear: "2026" });
  });
  it("falls back to the registry year", () => {
    expect(interpretHealth({ status: "healthy" }, "2025").revitYear).toBe("2025");
  });
  it("is not connected otherwise", () => {
    expect(interpretHealth({ status: "degraded" }).connected).toBe(false);
    expect(interpretHealth(null).connected).toBe(false);
  });
});
