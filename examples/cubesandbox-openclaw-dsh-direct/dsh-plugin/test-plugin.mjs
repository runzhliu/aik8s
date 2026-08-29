import assert from "node:assert/strict";
import { apply } from "./index.js";

const tools = [];
const prompts = [];
const calls = [];
const originalFetch = globalThis.fetch;

globalThis.fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  calls.push({ url, body, authorization: options.headers.authorization });
  if (url.endsWith("/v1/leases/acquire")) {
    return { ok: true, json: async () => ({ lease_ref: "lease_test", sandbox_ref: "12345678" }) };
  }
  return {
    ok: true,
    json: async () => ({ executor: "cubesandbox-microvm", sandbox_ref: "12345678", stdout: "remote-ok\n", exit_code: 0 }),
  };
};

try {
  const dispose = apply(
    {
      systemPrompt: { section: (value) => prompts.push(value) },
      tools: {
        register: (definition) => {
          tools.push(definition);
          return () => {};
        },
      },
    },
    { adapterUrl: "http://adapter.test", tokenEnv: "TEST_CUBE_TOKEN", profile: "offline-code" },
  );
  process.env.TEST_CUBE_TOKEN = "redacted-test-token";

  assert.deepEqual(tools.map((value) => value.name), ["cube_exec", "cube_read", "cube_write", "cube_release"]);
  assert.equal(prompts.length, 1);
  const result = await tools[0].execute(
    { command: "printf remote-ok" },
    { agent: { id: "session-42" }, rootCallId: "call-1", signal: new AbortController().signal },
  );
  assert.equal(result.executor, "cubesandbox-microvm");
  assert.equal(calls[0].body.session_key, "session-42");
  assert.equal(calls[0].body.runtime, "dsh");
  assert.equal(calls[1].body.command, "printf remote-ok");
  assert.equal(calls[0].authorization, "Bearer redacted-test-token");
  dispose();
  console.log("DSH Cube Adapter plugin test: OK");
} finally {
  globalThis.fetch = originalFetch;
  delete process.env.TEST_CUBE_TOKEN;
}
