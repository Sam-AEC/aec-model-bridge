import { createRequire } from "node:module";
import { afterEach, describe, expect, it, vi } from "vitest";

// Resolve through VSCE so this checks the overridden dependency it actually uses,
// including when npm nests its Azure packages instead of hoisting them.
const fromVsce = createRequire(require.resolve("@vscode/vsce/package.json"));
const fromIdentity = createRequire(fromVsce.resolve("@azure/identity"));
const { EnvironmentCredential } = fromVsce("@azure/identity");
const { ConfidentialClientApplication } = fromIdentity("@azure/msal-node");
const { createHttpHeaders } = fromIdentity("@azure/core-rest-pipeline");

const tenant = "11111111-1111-1111-1111-111111111111";
const clientId = "22222222-2222-2222-2222-222222222222";
const authority = `https://login.microsoftonline.com/${tenant}`;

afterEach(() => vi.unstubAllEnvs());

describe("VSCE's patched MSAL dependency", () => {
  it("supports Azure Identity client-secret authentication without network access", async () => {
    vi.stubEnv("AZURE_TENANT_ID", tenant);
    vi.stubEnv("AZURE_CLIENT_ID", clientId);
    vi.stubEnv("AZURE_CLIENT_SECRET", "synthetic-test-secret");
    vi.stubEnv("AZURE_AUTHORITY_HOST", "https://login.microsoftonline.com");

    const requests: Array<{ url: string; method: string; body?: unknown }> = [];
    const credential = new EnvironmentCredential({
      disableInstanceDiscovery: true,
      httpClient: {
        async sendRequest(request: { url: string; method: string; body?: unknown }) {
          requests.push(request);
          const url = new URL(request.url);
          const endpoint = `${url.origin}${url.pathname}`;
          let body: object;
          if (endpoint === `${authority}/v2.0/.well-known/openid-configuration`) {
            body = {
              authorization_endpoint: `${authority}/oauth2/v2.0/authorize`,
              token_endpoint: `${authority}/oauth2/v2.0/token`,
              issuer: `${authority}/v2.0`,
              jwks_uri: `${authority}/discovery/v2.0/keys`,
            };
          } else if (endpoint === `${authority}/oauth2/v2.0/token`) {
            body = {
              token_type: "Bearer",
              access_token: "synthetic-access-token",
              expires_in: 3600,
            };
          } else {
            throw new Error(`Unexpected authentication request: ${request.url}`);
          }
          return {
            request,
            status: 200,
            headers: createHttpHeaders({ "content-type": "application/json" }),
            bodyAsText: JSON.stringify(body),
          };
        },
      },
    });

    const token = await credential.getToken("499b84ac-1321-427f-aa17-267ca6975798/.default")
      .catch((cause: unknown) => {
        throw new Error(`Authentication failed after requests to ${requests.map((r) => r.url).join(", ")}`, { cause });
      });
    expect(token.token).toBe("synthetic-access-token");
    const tokenRequests = requests.filter((r) => r.method === "POST");
    expect(tokenRequests).toHaveLength(1);
    const payload = new URLSearchParams(String(tokenRequests[0].body));
    expect(payload.get("grant_type")).toBe("client_credentials");
    expect(payload.get("client_id")).toBe(clientId);
    expect(payload.get("client_secret")).toBe("synthetic-test-secret");
  });

  it("rejects instance-aware confidential clients implicated in GHSA-xcx6-jx8p-x3h5", () => {
    expect(() => new ConfidentialClientApplication({
      auth: { clientId, clientSecret: "synthetic-test-secret", authority, instanceAware: true },
    })).toThrow(/unsupported_cca_instance_aware/);
  });

  it("rejects instance-aware authorization requests before making HTTP calls", async () => {
    const client = new ConfidentialClientApplication({
      auth: { clientId, clientSecret: "synthetic-test-secret", authority },
    });
    await expect(client.getAuthCodeUrl({
      scopes: ["https://graph.microsoft.com/.default"],
      redirectUri: "http://localhost",
      extraQueryParameters: { instance_aware: "true" },
    })).rejects.toMatchObject({ errorCode: "unsupported_cca_instance_aware" });
  });
});
