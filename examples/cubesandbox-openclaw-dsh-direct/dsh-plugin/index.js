import { readFile } from "node:fs/promises";

export const name = "cube-adapter-tools";
export const inject = ["tools", "systemPrompt"];

async function settings(config) {
  const adapterUrl = String(config.adapterUrl || process.env.CUBE_ADAPTER_URL || "http://127.0.0.1:18080").replace(/\/$/, "");
  if (!/^https?:\/\//.test(adapterUrl)) throw new Error("Cube Adapter URL must use HTTP or HTTPS");
  const tokenEnv = String(config.tokenEnv || "CUBE_ADAPTER_TOKEN");
  let token = process.env[tokenEnv];
  if (!token && config.tokenFile) token = (await readFile(String(config.tokenFile), "utf8")).trim();
  if (!token) throw new Error(`${tokenEnv} or tokenFile is not configured`);
  return { adapterUrl, token, profile: String(config.profile || "offline-code") };
}

async function request(config, path, body, signal) {
  const { adapterUrl, token } = await settings(config);
  const response = await fetch(`${adapterUrl}${path}`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Cube Adapter ${response.status}: ${payload?.error?.message || "request failed"}`);
  return payload;
}

function sessionKey(exec) {
  return String(exec.agent?.id || exec.rootCallId || "dsh-agentless");
}

async function acquire(config, exec) {
  return request(
    config,
    "/v1/leases/acquire",
    {
      runtime: "dsh",
      session_key: sessionKey(exec),
      profile: String(config.profile || "offline-code"),
    },
    exec.signal,
  );
}

const output = {
  schema: { description: "Redacted Cube Adapter JSON response." },
  render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }],
};

const object = (properties, required = []) => ({
  type: "object",
  additionalProperties: false,
  properties,
  required,
});

function tool(name, description, parameters, run) {
  return {
    name,
    description,
    parameters,
    output,
    timeoutMs: 125000,
    async execute(args, exec) {
      const lease = await acquire(this?.config || {}, exec);
      return run(lease, args, exec);
    },
  };
}

export function apply(ctx, config = {}) {
  ctx.systemPrompt.section({
    name: "tool:cube-adapter",
    order: 104,
    text: "Use cube_exec, cube_read, and cube_write for shell and file work. They share one policy-controlled CubeSandbox MicroVM per DSH session. Call cube_release with pause when the user may continue or kill when the task is finished.",
  });

  const register = (definition) => {
    const bound = { ...definition, execute: definition.execute.bind({ config }) };
    return ctx.tools.register(bound);
  };
  const disposers = [
    register(
      tool(
        "cube_exec",
        "Execute a shell command inside this DSH session's isolated CubeSandbox MicroVM. Use it for untrusted code and shell work; the DSH host is not the execution target.",
        object(
          {
            command: { type: "string", description: "Shell command to execute in the MicroVM." },
            cwd: { type: "string", description: "Absolute /workspace or /tmp working directory." },
            timeout_ms: { type: "integer", description: "Timeout in milliseconds, capped by policy." },
          },
          ["command"],
        ),
        async (lease, args, exec) =>
          request(config, `/v1/leases/${lease.lease_ref}/exec`, args, exec.signal),
      ),
    ),
    register(
      tool(
        "cube_read",
        "Read a file from this DSH session's CubeSandbox /workspace or /tmp.",
        object({ path: { type: "string" } }, ["path"]),
        async (lease, args, exec) =>
          request(config, `/v1/leases/${lease.lease_ref}/read`, args, exec.signal),
      ),
    ),
    register(
      tool(
        "cube_write",
        "Write a UTF-8 file inside this DSH session's CubeSandbox /workspace or /tmp.",
        object({ path: { type: "string" }, content: { type: "string" } }, ["path", "content"]),
        async (lease, args, exec) =>
          request(config, `/v1/leases/${lease.lease_ref}/write`, args, exec.signal),
      ),
    ),
    register(
      tool(
        "cube_release",
        "Pause or destroy this DSH session's CubeSandbox lease.",
        object({ action: { type: "string", enum: ["pause", "kill"] } }),
        async (lease, args, exec) =>
          request(
            config,
            `/v1/leases/${lease.lease_ref}/release`,
            { action: args.action || "pause" },
            exec.signal,
          ),
      ),
    ),
  ];
  return () => disposers.reverse().forEach((dispose) => dispose());
}
