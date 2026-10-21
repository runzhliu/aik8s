# OpenKruise Agents 0.6.0 CPU sandbox lab

This directory reproduces the article's small functional experiment. The local
workbench is an SDK demonstration, **not an official OpenKruise Console**.
No model endpoint, GPU, node DaemonSet, runtime change, or checkpoint backend is
required for the exercised paths. Use a test cluster without an existing Agents
installation: the Charts contain fixed cluster-scoped resource names.

Requirements: Kubernetes 1.30.4 as tested (upstream minimum 1.28; native-sidecar
runtime injection needs 1.29), Helm, kubectl, Python, an NGINX Ingress controller,
and the packages in `requirements.txt`. All commands run from the repository root.
Set your kubectl context explicitly before applying resources.

```bash
python3 -m venv .local/kruise-venv
.local/kruise-venv/bin/python -m pip install -r examples/openkruise-agents/requirements.txt
git clone --depth 1 --branch v0.6.0 https://github.com/openkruise/agents.git .local/kruise-agents-source
git -C .local/kruise-agents-source rev-parse HEAD
# Expected: a1e0811323b71fd9a54efe26b0f4baf19106c84e

helm pull agents-sandbox-controller --repo https://openkruise.github.io/charts --version 0.6.0 --untar --untardir .local/kruise-charts
helm pull agents-sandbox-manager --repo https://openkruise.github.io/charts --version 0.6.0 --untar --untardir .local/kruise-charts
.local/kruise-venv/bin/python examples/openkruise-agents/render-lab.py \
  --charts .local/kruise-charts --output .local/kruise-agents-lab --test-node worker-lab
```

Replace `worker-lab` with your test node. Generated files include an admin key;
keep the output private. An optional `--image-map` JSON file can supply complete
image references for `agent-sandbox-controller`, `sandbox-manager`,
`sandbox-gateway`, `agent-runtime`, and `python`. Image sources and verified
upstream digests are recorded in `images.source-lock.json`; no private mirror
address is included here. In the tested containerd environment, digest-qualified
agent-runtime references blocked Stop resume; see the article and raw attempts
before choosing that reference form.

Review the generated manifests, then apply in order:

```bash
kubectl create namespace sandbox-system
kubectl apply --server-side --dry-run=server --field-manager=kruise-agents-lab -f .local/kruise-agents-lab/controller-crds.yaml
kubectl apply --server-side --field-manager=kruise-agents-lab -f .local/kruise-agents-lab/controller-crds.yaml
kubectl apply --dry-run=server -f .local/kruise-agents-lab/controller-install.yaml
kubectl apply -f .local/kruise-agents-lab/controller-install.yaml
kubectl -n sandbox-system rollout status deploy/agents-sandbox-controller --timeout=180s
kubectl apply --server-side --field-manager=kruise-agents-lab -f .local/kruise-agents-lab/manager-crds.yaml
kubectl apply --dry-run=server -f .local/kruise-agents-lab/manager-install.yaml
kubectl apply -f .local/kruise-agents-lab/manager-install.yaml
kubectl -n sandbox-system rollout status deploy/agents-sandbox-manager --timeout=180s
kubectl -n sandbox-system rollout status deploy/sandbox-gateway --timeout=180s
kubectl apply -f .local/kruise-agents-lab/python-pool.yaml
kubectl apply -f .local/kruise-agents-lab/python-cold.yaml
```

The renderer applies the experimental namespace to every namespaced object and
narrows webhook namespace selectors. CRDs and RBAC still have cluster-wide scope;
the controller is not a namespace-confined security principal. Installation uses
rendered manifests and client-side apply for runtime resources, not a Helm
release or server-side apply of the webhook annotations. Runtime TLS, Agentio,
snapshot hibernation, Commit, and PVC persistence are not enabled.

Forward your existing NGINX Ingress Service to localhost port 18882 in a separate
terminal. Its name and namespace depend on your installation. The rendered
Ingress serves the `localhost` host; no hosts-file edit is needed. Then:

```bash
export E2B_DOMAIN=localhost:18882
export E2B_API_KEY="$(cat .local/kruise-agents-lab/admin-api-key)"
.local/kruise-venv/bin/python examples/openkruise-agents/verify.py \
  --context your-test-context --upstream .local/kruise-agents-source \
  --output .local/kruise-agents-lab/validation.json
.local/kruise-venv/bin/python examples/openkruise-agents/workbench.py \
  --context your-test-context --upstream .local/kruise-agents-source \
  --output .local/kruise-agents-lab/workbench-runs.json
```

Open <http://127.0.0.1:18890/> and click the run button. It claims a real sandbox,
writes a Python script, executes it, and deletes the sandbox in cleanup. The
web application is localhost-only and keeps the admin key out of browser code.
The sample is a tool-execution demonstration, not a model-driven planning agent.

`verify.py` measures five warm and three zero-inventory creates, then checks file
separation, Stop resume, TTL, timeout validation, authentication, and replenishment.
It preserves individual failures and cleans up claimed sandboxes. The warm pool
remains at two replicas for interactive use. `--lifecycle-only` reruns the five
lifecycle/authentication checks without repeating the creation measurements.
See `results/README.json` for why three distinct attempt reports are retained.

For an existing VictoriaMetrics/Grafana installation, inspect `monitoring.yaml`
and `dashboard-configmap.json` before applying them. Their example namespace is
`victoriametrics`, scraper ServiceAccount `vmagent-vmks`, dashboard sidecar label
`victoriametrics_dashboard=1`, and datasource UID `VictoriaMetrics`. The manifests
add three scrapes and two dashboards; they do not change a Helm release. The
controller scrape uses bearer-token authentication with self-signed TLS; configure
a trusted CA instead of `insecureSkipVerify` for production.

To release experimental sandbox capacity, scale **both** SandboxSets to zero and
delete only this experiment's claimed Sandbox objects. Full component removal
should use the reviewed installation manifests. Do not delete CRDs until all
their instances have been inspected, because that removes the custom resources.
