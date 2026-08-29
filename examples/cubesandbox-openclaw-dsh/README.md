# CubeSandbox Skills for OpenClaw and DSH

This directory contains the minimal Skills used by the real OpenClaw and
DeepSeek Harness runs documented in
[`cubesandbox-openclaw-dsh-enterprise-practice.md`](../../docs/ai-k8s/rag-agent/cubesandbox-openclaw-dsh-enterprise-practice.md).

Both Skills use `cubesandbox==0.7.0` to:

1. create a short-lived MicroVM;
2. write and execute user-supplied Python in that MicroVM;
3. verify that public network access is blocked;
4. destroy the Sandbox in a `finally` block;
5. return a structured, redacted result.

The two copies differ only in their installation path, runtime metadata, and
temporary task filename:

- `openclaw-skill/cube-sandbox` targets an OpenClaw workspace;
- `dsh-skill/cube-sandbox` targets `DSH_HOME/skills`.

Provide the following environment variables to the Agent runtime instead of
putting endpoints or credentials in `SKILL.md`:

```text
CUBE_API_URL
CUBE_PROXY_NODE_IP
CUBE_PROXY_PORT_HTTP
CUBE_PROXY_SCHEME
CUBE_TEMPLATE_ID
```

`--hold-seconds` exists only for a live WebUI demonstration. Normal tasks
should use the default value of zero. This is a proof-oriented thin
integration, not a replacement for an enterprise Adapter with identity,
approval, quotas, audit events, lease persistence, and policy profiles.
