# GPU platform baseline

These manifests accompany the Chinese guide `docs/ai-k8s/guides/gpu-platform-lab.md`.

They require an existing Kubernetes cluster with an NVIDIA GPU node and the NVIDIA Device Plugin. Review image versions, node taints, storage, networking, and security policy before applying them outside a disposable lab namespace.

Apply in this order:

```bash
kubectl apply -f namespace.yaml
kubectl apply -f gpu-smoke-test.yaml
kubectl apply -f vllm-deployment.yaml
kubectl apply -f network-policy.yaml
```
