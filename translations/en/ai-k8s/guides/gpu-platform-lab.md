---
title: "Experiment: From GPU Node to Observable Inference Service"
description: "Complete node inspection, device smoke test, model deployment, metric verification, and failure drill on an existing GPU Kubernetes cluster."
status: lab
last_reviewed: 2026-08-02
tested_with:
  kubernetes: "1.34+"
  accelerator: "NVIDIA GPU through Device Plugin"
---

# Experiment: From GPU Node to Observable Inference Service

This experiment targets a Kubernetes cluster that already has an NVIDIA GPU worker. The goal is not to install the entire AI platform, but to establish a repeatable minimal validation path: node inventory, GPU containers, model serving, monitoring correlation, termination behavior, and evidence recording.

Example manifests are also stored in the repository at [`examples/gpu-platform-baseline`](https://github.com/runzhliu/aik8s/tree/main/examples/gpu-platform-baseline).

## 1. Prerequisites and Safety Notes

You need:

- Kubernetes 1.34 or newer;
- `kubectl`;
- At least one node with drivers and the NVIDIA Device Plugin installed;
- Ability to pull public test images;
- Permission to create Namespaces, Pods, Deployments, Services, and NetworkPolicies;
- Optional Prometheus/DCGM Exporter.

Example images and versions are for demonstration. Production environments must pin image digests, verify driver compatibility, and use an internal registry.

Do not perform failure experiments directly on nodes that host critical training or production inference.

## 2. Create an Experiment Namespace

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ai-lab
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

```bash
kubectl apply -f examples/gpu-platform-baseline/namespace.yaml
kubectl get namespace ai-lab --show-labels
```

Expected: Namespace is `Active`, and Pod Security labels exist.

## 3. Inspect GPU Inventory

```bash
kubectl get nodes -o custom-columns='NAME:.metadata.name,GPU:.status.capacity.nvidia\.com/gpu,ALLOCATABLE:.status.allocatable.nvidia\.com/gpu'
```

Inspect the target node:

```bash
kubectl describe node <gpu-node>
kubectl get pods -A -o wide --field-selector spec.nodeName=<gpu-node>
```

Record:

- GPU Capacity/Allocatable;
- GPU product and topology labels;
- Taints;
- Device Plugin, DCGM, and CNI DaemonSets;
- Allocated GPUs;
- CPU, memory, and ephemeral storage.

If the GPU column is empty, fix the Driver/Device Plugin first and do not continue with model experiments.

## 4. Run GPU Smoke Test

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-smoke-test
  namespace: ai-lab
spec:
  restartPolicy: Never
  containers:
    - name: vector-add
      image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
      resources:
        requests:
          cpu: "1"
          memory: 512Mi
          nvidia.com/gpu: "1"
        limits:
          cpu: "1"
          memory: 512Mi
          nvidia.com/gpu: "1"
```

If the GPU node has a dedicated taint, add a toleration consistent with the platform convention in the manifest. Do not use a broad `operator: Exists` to bypass all taints.

```bash
kubectl apply -f examples/gpu-platform-baseline/gpu-smoke-test.yaml
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-smoke-test -n ai-lab --timeout=5m
kubectl logs -n ai-lab gpu-smoke-test
kubectl describe pod -n ai-lab gpu-smoke-test
```

Expected logs contain test pass information. Save Pod YAML, events, and logs as acceptance evidence.

## 5. Observe Device Ownership

While the smoke test runs, or for long-running tests, check:

```bash
kubectl get pod -n ai-lab -o wide
kubectl get pod -n ai-lab gpu-smoke-test -o jsonpath='{.metadata.uid}{"\n"}'
```

If DCGM Exporter is installed, confirm in Prometheus that metrics can be correlated to:

- Node;
- Namespace;
- Pod;
- Container;
- GPU UUID/Index.

Seeing only node-level GPU utilization is insufficient for multi-tenant billing and troubleshooting.

## 6. Deploy a Minimal Inference Service

The following example uses vLLM and a small model to express only the Deployment baseline. GPU memory, image tags, and engine parameters must be adjusted according to the actual environment.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-server
  namespace: ai-lab
spec:
  replicas: 1
  selector:
    matchLabels:
      app: llm-server
  template:
    metadata:
      labels:
        app: llm-server
    spec:
      terminationGracePeriodSeconds: 120
      containers:
        - name: vllm
          image: vllm/vllm-openai:v0.11.1
          args:
            - --model=Qwen/Qwen2.5-0.5B-Instruct
            - --served-model-name=lab-model
            - --max-model-len=4096
          ports:
            - name: http
              containerPort: 8000
          startupProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 10
            failureThreshold: 60
          readinessProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 5
          resources:
            requests:
              cpu: "2"
              memory: 8Gi
              nvidia.com/gpu: "1"
            limits:
              cpu: "2"
              memory: 8Gi
              nvidia.com/gpu: "1"
          volumeMounts:
            - name: dshm
              mountPath: /dev/shm
      volumes:
        - name: dshm
          emptyDir:
            medium: Memory
            sizeLimit: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: llm-server
  namespace: ai-lab
spec:
  selector:
    app: llm-server
  ports:
    - name: http
      port: 8000
      targetPort: http
```

```bash
kubectl apply -f examples/gpu-platform-baseline/vllm-deployment.yaml
kubectl rollout status deployment/llm-server -n ai-lab --timeout=15m
kubectl get pod -n ai-lab -o wide
kubectl logs -n ai-lab deployment/llm-server --tail=100
```

The first startup requires pulling the model. Do not use this experiment's public download method directly in production.

## 7. Send Requests

```bash
kubectl port-forward -n ai-lab service/llm-server 8000:8000
```

In another terminal:

```bash
curl -sS http://127.0.0.1:8000/v1/models

curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "lab-model",
    "messages": [{"role": "user", "content": "用一句话解释 Kubernetes。"}],
    "max_tokens": 64,
    "temperature": 0
  }'
```

Verify: HTTP status, returned model name, first token, completion reason, and token usage.

Port forwarding is only for functional verification and does not represent production gateway performance.

## 8. Record Cold Start

Delete the Pod to trigger recreation:

```bash
kubectl get pod -n ai-lab -l app=llm-server
kubectl delete pod -n ai-lab -l app=llm-server
kubectl get pod -n ai-lab -l app=llm-server -w
```

Record:

- Scheduler to node time;
- Image pull;
- Model download;
- Model loading;
- Startup/Readiness success;
- Service endpoint ready.

The first time is a cache cold start; the second time may hit image and model caches. Save both.

## 9. Verify Termination Behavior

Execute during a continuous streaming request:

```bash
kubectl rollout restart deployment/llm-server -n ai-lab
kubectl rollout status deployment/llm-server -n ai-lab --timeout=15m
```

Observe:

- When the old Pod leaves the Service endpoint;
- Whether the streaming request completes or fails explicitly;
- Time from SIGTERM to process exit;
- When the new Pod becomes Ready;
- Whether there is a moment with no Ready replicas.

Single-replica experiments risk interruption. Production should use multiple replicas, PDBs, topology spread, and controlled rolling update strategies.

## 10. Basic NetworkPolicy

This experiment can apply default deny ingress, then allow only the same Namespace:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: llm-server-ingress
  namespace: ai-lab
spec:
  podSelector:
    matchLabels:
      app: llm-server
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ai-lab
      ports:
        - protocol: TCP
          port: 8000
```

Confirm that the CNI actually supports and enforces NetworkPolicy. Production should also restrict egress, object storage, DNS, and metadata services.

## 11. Evidence Template

```text
Date:
Cluster / Kubernetes:
Node / GPU:
OS / kernel / driver:
Device Plugin / GPU Operator:
Runtime image digest:
Model revision:
Smoke test result:
Cold start (cold cache):
Cold start (warm cache):
TTFT / TPOT baseline:
GPU metrics mapping:
Rollout/termination result:
NetworkPolicy result:
Known deviations:
Evidence location:
```

## 12. Cleanup

```bash
kubectl delete namespace ai-lab
```

Confirm that experiment Pods, Services, NetworkPolicies, and temporary model caches have been cleaned up according to platform policy. Whether local node caches are retained is determined by the cache controller.

## 13. Acceptance Criteria

- [ ] Kubernetes correctly reports GPU Capacity/Allocatable.
- [ ] GPU smoke test completed and logs/events saved.
- [ ] GPU metrics can be correlated to Pods and physical devices.
- [ ] Inference service becomes Ready only after the model is actually loaded.
- [ ] A request successfully completes via the OpenAI-compatible API.
- [ ] Time data exists for each phase of cold/hot start.
- [ ] Rolling update and streaming request behavior have been observed.
- [ ] Both allow and deny paths of NetworkPolicy are verified.
- [ ] All image and model versions are recorded in evidence.
- [ ] Experiment resources can be fully cleaned up.

## Next Steps

After completing this experiment, you can add in order:

1. Kueue queues and GPU Flavor;
2. KServe InferenceService;
3. LocalModelCache or OCI Modelcar;
4. KEDA custom metric scaling;
5. Gateway API Inference Extension;
6. Multi-replica failure and node drain;
7. Real model load benchmark.
