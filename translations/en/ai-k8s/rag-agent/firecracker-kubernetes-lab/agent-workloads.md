# Agent Workloads on Kata + Firecracker

This experiment runs OpenClaw, DSH, Hermes, and Codex as ordinary Kubernetes Pods, with the runtime selected via
`runtimeClassName: kata-fc-lab`. Each Pod therefore has a
Kata/Firecracker microVM isolation boundary around it. The Agent's CubeSandbox integration then requests a separate sandbox through the Adapter API:

```text
Kubernetes Pod
  -> Kata runtime-rs
  -> Firecracker microVM（Agent 运行时）
  -> Agent 的 CubeSandbox 插件或 MCP 客户端
  -> CubeSandbox Adapter
  -> CubeSandbox 沙箱（工具执行）
```

The intent here is to verify the combination of the two systems, not to treat them as substitutes for one another. Firecracker provides the Pod isolation boundary, while CubeSandbox provides the Agent-facing execution API and sandbox lifecycle.

## Test Results

| Application | Version | Verification Path | Result |
| --- | --- | --- | --- |
| OpenClaw | 2026.8.2 | Plugin discovery, model conversation, `cube_exec`, `cube_status`, `cube_release` | Passed; 3 tool calls succeeded, 0 failed |
| DSH | 0.1.2-alpha.4 | Headless Agent run and CubeSandbox plugin tools | Passed; returned execution marker and released sandbox |
| Hermes | 0.21.0 | Plugin diagnostics, single model run, CubeSandbox lifecycle | Passed; plugin detected, execution marker returned, audit chain complete |
| Codex | 0.150.1 | Adapter client and official MCP stdio handshake | Partially passed; all 17 MCP tools discovered, lifecycle smoke test passed; no model conversation run |

No artificially successful result was manufactured for Codex. Its custom model provider currently requires the Responses protocol, while the gateway in the experimental environment only offers Chat Completions. The Adapter and MCP integration were therefore verified independently instead.

![Redacted Agent test results matrix](assets/evidence/agents-light.jpg)

## Reproducible Deployment Structure

[`manifests/kata-fc-agents.yaml`](manifests/kata-fc-agents.yaml) contains the redacted
Pod definitions. Before applying, the following objects must be provided by the environment side, and their real values must not be committed to the repository:

- `Secret/firecracker-agent-model`: contains the model endpoint and credential environment variables required by the selected Agent;
- `Secret/cube-adapter-auth`: contains the key `token`;
- four `firecracker-*-plugin` ConfigMaps generated from the corresponding plugin versions;
- an accessible CubeSandbox Adapter service, plus the four pinned-version workload images already loaded into the node-local image registry or an approved registry.

The manifests pass credentials in via Secret references, remove Linux capabilities, disallow privilege escalation, use the runtime default seccomp configuration, and allocate a separate `emptyDir` workspace for each application.

```bash
kubectl apply -f manifests/kata-fc-agents.yaml
kubectl wait -n agent-runtime --for=condition=Ready \
  pod/kata-fc-openclaw pod/kata-fc-dsh pod/kata-fc-hermes pod/kata-fc-codex \
  --timeout=300s
kubectl get pod -n agent-runtime -l app.kubernetes.io/part-of=firecracker-agent-lab -o wide
```

The boundary must be verified from both the inside and the outside: `kubectl exec` should return Kata Guest kernel information; on the Worker node, a Firecracker VMM should be visible for each Pod.

## Compatibility Findings

The Kata TAP network under test cannot reach the cluster's regular ClusterIP, but can directly reach Pod addresses. The isolated Worker also cannot reach the model endpoint, so an access-controlled SSH reverse forward was used temporarily during testing and removed afterward. These are network integration issues, not Firecracker failures. Production environments should fix CNI/Service routing and use an authenticated internal egress path, rather than keeping a forwarding tunnel long-term.

Mounting the Agent's entire state directory to `emptyDir` also triggered `fchmod`
compatibility issues in two images. The test therefore kept application state in the container root filesystem and mounted only workspaces or known-compatible state paths. Ownership-change behavior must be re-verified before converting these mounts to persistent storage.

## Light Mode Application Screenshots

The following four images are genuine light mode product screenshots from the same CubeSandbox application integration, copied into this standalone release package. The new Firecracker results for this release are represented by the redacted measurement chart and audit results above; these UI screenshots do not pose as Firecracker console views.

### OpenClaw

![OpenClaw using CubeSandbox](assets/apps/openclaw-cubesandbox-light.jpg)

### DSH

![DSH using CubeSandbox](assets/apps/dsh-cubesandbox-light.png)

### Hermes

![Hermes using CubeSandbox](assets/apps/hermes-cubesandbox-light.png)

### Codex

![Codex using CubeSandbox](assets/apps/codex-cubesandbox-light.png)

## Cleanup Checks

After each Agent task completes, both the application output and the Adapter release audit record must be used as the basis for cleanup verification. At the end of all tests, the Adapter reported 0 active leases. Seeing only a successful text response does not prove that the sandbox has been fully cleaned up.
