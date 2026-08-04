---
title: 实验：从 GPU 节点到可观测推理服务
description: 在已有 GPU Kubernetes 集群上完成节点检查、设备 Smoke Test、模型部署、指标验证和故障演练
status: lab
last_reviewed: 2026-08-02
tested_with:
  kubernetes: "1.34+"
  accelerator: "NVIDIA GPU through Device Plugin"
---

# 实验：从 GPU 节点到可观测推理服务

本实验面向已经有一台 NVIDIA GPU Worker 的 Kubernetes 集群。目标不是安装全部 AI 平台，而是建立一条可重复的最小验证路径：节点库存、GPU 容器、模型服务、监控关联、终止行为和证据记录。

示例 Manifest 同时保存在仓库的 [`examples/gpu-platform-baseline`](https://github.com/runzhliu/aik8s/tree/main/examples/gpu-platform-baseline)。

## 1. 前提和安全说明

需要：

- Kubernetes 1.34 或更新版本；
- `kubectl`；
- 至少一个已经安装驱动和 NVIDIA Device Plugin 的节点；
- 能拉取公开测试镜像；
- 有权限创建 Namespace、Pod、Deployment、Service 和 NetworkPolicy；
- 可选 Prometheus/DCGM Exporter。

示例镜像和版本用于演示。生产环境必须固定镜像 Digest、核对驱动兼容并使用内部 Registry。

不要在承载重要训练或生产推理的节点上直接进行故障实验。

## 2. 建立实验 Namespace

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

预期：Namespace 为 `Active`，Pod Security 标签存在。

## 3. 检查 GPU 库存

```bash
kubectl get nodes -o custom-columns='NAME:.metadata.name,GPU:.status.capacity.nvidia\.com/gpu,ALLOCATABLE:.status.allocatable.nvidia\.com/gpu'
```

检查目标节点：

```bash
kubectl describe node <gpu-node>
kubectl get pods -A -o wide --field-selector spec.nodeName=<gpu-node>
```

记录：

- GPU Capacity/Allocatable；
- GPU 产品和拓扑标签；
- Taint；
- Device Plugin、DCGM 和 CNI DaemonSet；
- 已分配 GPU；
- CPU、内存和临时存储。

如果 GPU 列为空，先修复 Driver/Device Plugin，不继续模型实验。

## 4. 运行 GPU Smoke Test

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

如果 GPU 节点有专用 Taint，在 Manifest 中加入与平台约定一致的 Toleration，不要用宽泛 `operator: Exists` 绕过所有 Taint。

```bash
kubectl apply -f examples/gpu-platform-baseline/gpu-smoke-test.yaml
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-smoke-test -n ai-lab --timeout=5m
kubectl logs -n ai-lab gpu-smoke-test
kubectl describe pod -n ai-lab gpu-smoke-test
```

预期日志包含测试通过信息。保存 Pod YAML、Event 和日志作为验收证据。

## 5. 观察设备归属

Smoke Test 运行时或对长运行测试，检查：

```bash
kubectl get pod -n ai-lab -o wide
kubectl get pod -n ai-lab gpu-smoke-test -o jsonpath='{.metadata.uid}{"\n"}'
```

如果安装 DCGM Exporter，在 Prometheus 中确认指标能关联：

- Node；
- Namespace；
- Pod；
- Container；
- GPU UUID/Index。

只看到节点级 GPU 利用率还不足以完成多租户计费和排障。

## 6. 部署最小推理服务

以下示例使用 vLLM 和小模型，只表达 Deployment 基线。GPU 显存、镜像 Tag 和引擎参数必须按实际环境调整。

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

首次启动需要拉取模型。不要把本实验的公网下载方式直接用于生产。

## 7. 发送请求

```bash
kubectl port-forward -n ai-lab service/llm-server 8000:8000
```

另一个终端：

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

验证：HTTP 状态、返回模型名、首 Token、完成原因和 Token 使用量。

Port Forward 仅用于功能验证，不能代表生产 Gateway 的性能。

## 8. 记录冷启动

删除 Pod 触发重建：

```bash
kubectl get pod -n ai-lab -l app=llm-server
kubectl delete pod -n ai-lab -l app=llm-server
kubectl get pod -n ai-lab -l app=llm-server -w
```

记录：

- scheduler 到节点时间；
- Image Pull；
- 模型下载；
- 模型加载；
- Startup/Readiness 成功；
- Service Endpoint Ready。

第一次是缓存冷启动，第二次可能命中镜像和模型缓存。两者都要保存。

## 9. 验证终止行为

在持续流式请求期间执行：

```bash
kubectl rollout restart deployment/llm-server -n ai-lab
kubectl rollout status deployment/llm-server -n ai-lab --timeout=15m
```

观察：

- 旧 Pod 何时离开 Service Endpoint；
- 流式请求是否完成或明确失败；
- SIGTERM 到进程退出时间；
- 新 Pod 何时 Ready；
- 是否出现同时无 Ready 副本。

单副本实验会有中断风险。生产应使用多个副本、PDB、拓扑分散和受控滚动策略。

## 10. 基础 NetworkPolicy

本实验可以应用默认拒绝入站，再仅允许同 Namespace：

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

确认 CNI 实际支持并执行 NetworkPolicy。生产还应限制出站、对象存储、DNS 和元数据服务。

## 11. 证据模板

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

## 12. 清理

```bash
kubectl delete namespace ai-lab
```

确认实验 Pod、Service、NetworkPolicy 和临时模型缓存已按平台策略清理。本地节点缓存是否保留由缓存控制器决定。

## 13. 通过标准

- [ ] Kubernetes 正确报告 GPU Capacity/Allocatable。
- [ ] GPU Smoke Test 完成并保存日志/Event。
- [ ] GPU 指标能关联到 Pod 和物理设备。
- [ ] 推理服务只有模型真正加载后才 Ready。
- [ ] 一次请求通过 OpenAI-Compatible API 成功完成。
- [ ] 冷/热启动各阶段有时间数据。
- [ ] 滚动发布和流式请求行为已经观察。
- [ ] NetworkPolicy 的允许与拒绝路径均验证。
- [ ] 所有镜像和模型版本记录在证据中。
- [ ] 实验资源能够完整清理。

## 下一步

完成本实验后，可以依次加入：

1. Kueue 队列和 GPU Flavor；
2. KServe InferenceService；
3. LocalModelCache 或 OCI Modelcar；
4. KEDA 自定义指标扩缩容；
5. Gateway API Inference Extension；
6. 多副本故障和节点 Drain；
7. 真实模型负载基准。
