# OpenClaw / DSH direct CubeSandbox integration

This example replaces the earlier prompt-driven Skill route with runtime
plugins. Both plugins call one authenticated Adapter; only the Adapter can see
Cube credentials, full sandbox IDs and traffic tokens.

```text
OpenClaw Tool Plugin ─┐
                     ├─ Bearer auth → Cube Adapter → Cube SDK → MicroVM
DSH Cordis Plugin ───┘                    │
                                         └─ redacted JSONL audit
```

The implementation intentionally starts with one fail-closed policy profile:
`offline-code`. A model cannot submit CIDRs, public-traffic settings, template
IDs or lifecycle policy. File operations are restricted to `/workspace` and
`/tmp`; commands, files, outputs and timeouts have hard size limits.

## 1. Start the Adapter

The Python SDK reads its Cube connection settings directly. The `CUBE_PROXY_*`
variables are needed when the runtime cannot resolve the wildcard sandbox
domain and should dial CubeProxy explicitly.

```bash
python3 -m venv .venv
.venv/bin/pip install -r adapter/requirements.txt

export CUBE_API_URL=http://127.0.0.1:13000
export CUBE_PROXY_NODE_IP=127.0.0.1
export CUBE_PROXY_PORT_HTTP=13080
export CUBE_TEMPLATE_ID=agent-code
export CUBE_ADAPTER_TOKEN="$(openssl rand -hex 32)"
export CUBE_ADAPTER_HMAC_KEY="$(openssl rand -hex 32)"
export CUBE_ADAPTER_AUDIT_LOG=/var/log/cube-adapter/audit.jsonl

.venv/bin/python adapter/cube_adapter.py
```

`GET /healthz` is unauthenticated for probes. Every mutating endpoint requires
`Authorization: Bearer …`. The optional `/audit` demo page is disabled by
default; set `CUBE_ADAPTER_AUDIT_UI=1` only on a protected test network.
Keep `CUBE_ADAPTER_HMAC_KEY` independent from the bearer token so normal token
rotation does not change stable, pseudonymous session correlations.

The example Kubernetes deployment expects an existing Secret:

```bash
kubectl -n agent-runtime create secret generic cube-adapter-auth \
  --from-literal=token="$(openssl rand -hex 32)" \
  --from-literal=hmac-key="$(openssl rand -hex 32)"
kubectl apply -f deploy/kubernetes.yaml
```

Replace the placeholder image first. In production, send the JSONL stream to a
durable audit pipeline instead of the sample `emptyDir`, terminate mTLS at the
service mesh or gateway, and replace the in-process lease store with a durable
owner service before running more than one replica. The manifest deliberately
uses one replica: scale out only after leases, traffic tokens and ownership can
be recovered or routed consistently across replicas.

## 2. Install the OpenClaw Tool Plugin

```bash
openclaw plugins install ./openclaw-plugin
openclaw plugins enable cube-adapter-tools
openclaw config set tools.alsoAllow \
  '["cube_exec","cube_read","cube_write","cube_release"]' --strict-json
openclaw config validate
```

Give the Gateway process these environment variables, then restart it:

```bash
export CUBE_ADAPTER_URL=http://cube-adapter.agent-runtime.svc:18080
export CUBE_ADAPTER_TOKEN=<from-secret-manager>
```

The plugin registers `cube_exec`, `cube_read`, `cube_write` and
`cube_release`. Its factory derives the lease key from OpenClaw's current
`sessionKey`; the model never supplies a lease or Sandbox ID.

If `plugins.allow` is present, merge `cube-adapter-tools` into the existing
trusted-plugin list. Likewise, merge the four names into an existing
`tools.alsoAllow` list instead of overwriting unrelated policy. A plugin can be
loaded successfully yet remain unavailable to the model when this tool
allowlist is missing.

For a hardened Agent profile, deny host execution/file tools and allow the four
Cube tools. Keep administrative sessions separate instead of granting the same
profile both host tools and remote tools.

## 3. Install the DSH Cordis Plugin

```bash
dsh plugin --profile web add ./dsh-plugin
dsh web --patch ./dsh-plugin/cordis.patch.yml
```

Set `CUBE_ADAPTER_URL` and `CUBE_ADAPTER_TOKEN` on the DSH process, or mount a
Secret file and set `tokenFile` in the patch. The plugin uses `exec.agent.id`,
which is the durable DSH session ID, as its lease key.
The included patch disables the model-facing host Bash, PowerShell, FS search,
FS and string-replace editor plugins, then registers the same four Cube tools.
Review the composed profile and also disable any extra persistent-shell or
third-party host tools installed by your own bundle.

DSH's local `file:` install copies the package into its plugin store. Re-run the
plugin add/update step after editing the source directory; restarting DSH alone
does not refresh a stale installed copy.

## 4. API contract

```text
POST /v1/leases/acquire
POST /v1/leases/{lease_ref}/exec
POST /v1/leases/{lease_ref}/read
POST /v1/leases/{lease_ref}/write
POST /v1/leases/{lease_ref}/release
```

`acquire` is idempotent per `(runtime, HMAC-SHA-256(session_key))`. Responses expose
only a random `lease_ref` and eight-character `sandbox_ref`. Audit rows contain
the runtime, hashed session, policy, action, request ID, short Sandbox reference,
duration, outcome and command/path digest. They deliberately omit:

- bearer and traffic tokens;
- raw session keys;
- full Sandbox IDs;
- command text, file contents, stdout and stderr.

## 5. Verify

```bash
.venv/bin/python -m unittest -v adapter/test_cube_adapter.py
node --check openclaw-plugin/index.js
node --check dsh-plugin/index.js
node dsh-plugin/test-plugin.mjs
```

An end-to-end test should prove all three views agree on the same short
`sandbox_ref`: the Agent tool result, CubeSandbox's live Sandbox list and the
Adapter audit event. After `cube_release(action=kill)`, the live list should
return to zero.

## Upstream contribution boundary

The Adapter and two product plugins are deliberately independent packages and
contain no private registry, cluster, account or gateway assumptions. Likely
upstream contributions are:

- CubeSandbox: a maintained Agent Adapter example and stronger reconnect token
  support in the SDK;
- OpenClaw: this Tool Plugin now; a native fourth sandbox backend only after a
  stable public backend extension contract exists;
- DSH: this Cordis tool plugin now; later promote the Adapter client into
  `shell/fs/pty` providers once their remote-owner lifecycle contract is stable.
