# OpenSandbox 1.1.1 Kubernetes lab

This is a sanitized reproduction of the documented experiment. It uses the
upstream charts from commit `531700ca18a7fa5fab6a2f25d6dc68a76eddab12`.
Private registry mirrors, addresses, credentials, and local cluster access files
are intentionally absent.

Requirements: Python with `PyYAML` and `opensandbox==1.1.1`, Helm, kubectl, and a
test cluster. Review the generated manifests before applying them.

```bash
git clone --depth 1 --branch release-1.1.1 \
  https://github.com/opensandbox-group/OpenSandbox.git /tmp/OpenSandbox
export OPENSANDBOX_SOURCE=/tmp/OpenSandbox
export OPENSANDBOX_OUTPUT=/tmp/opensandbox-lab
# Optional: export OPENSANDBOX_TEST_NODE=your-test-node
python render-lab.py
kubectl create namespace opensandbox-lab
kubectl apply --server-side --field-manager=opensandbox-lab \
  -f /tmp/opensandbox-lab/crds.yaml
kubectl apply --dry-run=server -f /tmp/opensandbox-lab/install.yaml -o name
kubectl apply -f /tmp/opensandbox-lab/install.yaml
```

Run these forwards in separate terminals:

```bash
kubectl -n opensandbox-lab port-forward svc/opensandbox-server 38080:80
kubectl -n opensandbox-lab port-forward svc/opensandbox-ingress-gateway 38089:80
```

The renderer generates an API key and route signing key under the private output
directory. Set `OPENSANDBOX_API_KEY` from its `api-key` file through your preferred
secret-loading method, then run `python verify.py`. Never commit generated files.

The lab uses one server, one controller, one gateway, container-backed sandboxes,
and ephemeral SQLite storage. It installs seven CRDs but no Fast Sandbox runtime
or node DaemonSet. Controller writes are namespace-scoped; its upstream caches
retain cluster-wide reads, including Secret reads. This is not a production
multi-tenant security design. The image-committer configuration is unused here;
snapshot/pause/resume paths are not qualified by this lab.

The developer Console is a separate main-branch component at commit
`834c839dcf587784c16449aed56c21a5cf71b6d1`; see the article for the explicitly
tested compatibility boundary. `render-lab.py` does not deploy the Console.

For an existing VictoriaMetrics Operator and Grafana installation, review
`monitoring.yaml` and `dashboard-configmap.json`. The example assumes namespace
`victoriametrics`, Grafana sidecar label `victoriametrics_dashboard=1`, and data
source UID `VictoriaMetrics`; adjust those to your installation. Applying these
resources adds one scrape and one dashboard without changing the monitoring
Helm release. It does not install a monitoring stack.
