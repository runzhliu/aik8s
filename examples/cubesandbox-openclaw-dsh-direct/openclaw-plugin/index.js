import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

const DEFAULT_URL = "http://127.0.0.1:18080";

function settings(config) {
  const adapterUrl = String(config.adapterUrl || process.env.CUBE_ADAPTER_URL || DEFAULT_URL).replace(/\/$/, "");
  if (!/^https?:\/\//.test(adapterUrl)) throw new Error("Cube Adapter URL must use HTTP or HTTPS");
  const tokenEnv = String(config.tokenEnv || "CUBE_ADAPTER_TOKEN");
  const token = process.env[tokenEnv];
  if (!token) throw new Error(`${tokenEnv} is not configured`);
  return { adapterUrl, token, profile: String(config.profile || "offline-code") };
}

function sessionKey(toolContext) {
  return String(
    toolContext.sessionKey ||
      toolContext.agentId ||
      `openclaw:${toolContext.workspaceDir || "default"}`,
  );
}

async function request(config, toolContext, path, body, signal) {
  const { adapterUrl, token } = settings(config);
  const response = await fetch(`${adapterUrl}${path}`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`Cube Adapter ${response.status}: ${payload?.error?.message || "request failed"}`);
  }
  return payload;
}

async function acquire(config, toolContext, signal) {
  return request(
    config,
    toolContext,
    "/v1/leases/acquire",
    {
      runtime: "openclaw",
      session_key: sessionKey(toolContext),
      profile: String(config.profile || "offline-code"),
    },
    signal,
  );
}

function dynamicTool(definition, execute) {
  return {
    ...definition,
    factory: ({ config, toolContext }) => ({
      ...definition,
      execute: async (_toolCallId, params, signal) => {
        const lease = await acquire(config, toolContext, signal);
        const result = await execute(config, toolContext, lease, params, signal);
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          details: result,
        };
      },
    }),
  };
}

const object = (properties, required = []) => ({
  type: "object",
  additionalProperties: false,
  properties,
  required,
});

export default defineToolPlugin({
  id: "cube-adapter-tools",
  name: "CubeSandbox Adapter Tools",
  description: "Run untrusted Agent work in a policy-controlled CubeSandbox MicroVM.",
  configSchema: object({
    adapterUrl: { type: "string", description: "Cube Adapter base URL." },
    tokenEnv: { type: "string", description: "Environment variable containing the bearer token." },
    profile: { type: "string", enum: ["offline-code"], description: "Platform-owned policy profile." },
  }),
  tools: (tool) => [
    tool(
      dynamicTool(
        {
          name: "cube_exec",
          label: "CubeSandbox Exec",
          description: "Execute a shell command inside this conversation's isolated CubeSandbox MicroVM. Use this for untrusted code and shell work; the host is not the execution target.",
          parameters: object(
            {
              command: { type: "string", description: "Shell command to run inside the MicroVM." },
              cwd: { type: "string", description: "Absolute /workspace or /tmp working directory." },
              timeout_ms: { type: "integer", minimum: 1, maximum: 120000 },
            },
            ["command"],
          ),
        },
        (config, toolContext, lease, params, signal) =>
          request(config, toolContext, `/v1/leases/${lease.lease_ref}/exec`, params, signal),
      ),
    ),
    tool(
      dynamicTool(
        {
          name: "cube_read",
          label: "CubeSandbox Read",
          description: "Read a file from this conversation's CubeSandbox /workspace or /tmp.",
          parameters: object({ path: { type: "string" } }, ["path"]),
        },
        (config, toolContext, lease, params, signal) =>
          request(config, toolContext, `/v1/leases/${lease.lease_ref}/read`, params, signal),
      ),
    ),
    tool(
      dynamicTool(
        {
          name: "cube_write",
          label: "CubeSandbox Write",
          description: "Write a UTF-8 file inside this conversation's CubeSandbox /workspace or /tmp.",
          parameters: object(
            { path: { type: "string" }, content: { type: "string" } },
            ["path", "content"],
          ),
        },
        (config, toolContext, lease, params, signal) =>
          request(config, toolContext, `/v1/leases/${lease.lease_ref}/write`, params, signal),
      ),
    ),
    tool(
      dynamicTool(
        {
          name: "cube_release",
          label: "CubeSandbox Release",
          description: "Pause or destroy this conversation's CubeSandbox lease. Prefer pause when the user may continue and kill when the task is complete.",
          parameters: object({ action: { type: "string", enum: ["pause", "kill"] } }),
        },
        (config, toolContext, lease, params, signal) =>
          request(
            config,
            toolContext,
            `/v1/leases/${lease.lease_ref}/release`,
            { action: params.action || "pause" },
            signal,
          ),
      ),
    ),
  ],
});
