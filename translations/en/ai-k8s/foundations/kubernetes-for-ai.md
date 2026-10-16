---
title: "How Kubernetes Carries AI Workloads"
description: "Understanding the complete execution path of AI workloads in Kubernetes from controllers, scheduling, devices, networking, and storage"
status: stable
last_reviewed: 2026-08-02
---

# How Kubernetes Carries AI Workloads

Kubernetes does not understand "training," "inference," or "models." What it understands first is the declarative API, Pods, resources, controllers, and nodes. AI platforms build device discovery, gang scheduling, training lifecycles, model distribution, and request-level scheduling on top of this common foundation.

Understanding the responsibility of each layer is the starting point for troubleshooting AI platform issues. Otherwise, it is easy to blame the scheduler for a model loading failure, or mistake a GPU node creation failure for insufficient Kueue quota.

## 1. Complete Execution Path

```text
用户提交 TrainJob / RayJob / InferenceService / Deployment
                    │
                    ▼
Operator / Controller 将高层 API 转换为 Pod、Service 等资源
                    │
                    ▼
Kueue 等准入控制决定工作负载何时可以使用配额
                    │
                    ▼
kube-scheduler 根据资源、拓扑、亲和性和约束选择节点
                    │
                    ▼
Device Plugin 或 DRA Driver 分配 GPU、NIC 等设备
                    │
                    ▼
kubelet 通过 CRI 请求 containerd / CRI-O 创建容器
                    │
                    ▼
CNI 配置网络，CSI 挂载卷，Runtime 注入设备和驱动库
                    │
                    ▼
训练框架或推理引擎加载代码、数据和模型并开始计算
```

Every layer in this chain has independent state. When you see a Pod in `Pending`, first confirm whether it has been admitted by the queue, then look at scheduler events; when a container has started but `torch.cuda.is_available()` is false, focus on device allocation, the Runtime, and the container image.

## 2. What Kubernetes Native Objects Are Responsible For

| Object | Primary Responsibility | Typical Usage in AI Scenarios |
| --- | --- | --- |
| Pod | Smallest unit of scheduling and execution | Single training worker, inference replica, data processing step |
| Job | Runs to completion and records success/failure | Single-node training, batch inference, model conversion |
| Deployment | Maintains stateless replicas and rolling updates | Single-node inference engine, gateway, control service |
| StatefulSet | Stable identity and ordered lifecycle | Vector database, metadata service, some distributed systems |
| Service | Stable Layer-4 access entry point | Inference service, training Rendezvous, internal database |
| Gateway / HTTPRoute | Layer-7 entry point and traffic policy | Model API, tenant routing, Canary |
| ConfigMap / Secret | Configuration and sensitive values | Engine parameters, object storage credentials, model access tokens |
| PersistentVolumeClaim | Persistent volume claim | Notebook workspace, model cache, Checkpoint |
| RuntimeClass | Selects container isolation implementation | runc, gVisor, Kata, confidential containers |
| PriorityClass | Pod scheduling priority | Online inference capacity protection, urgent training |
| ResourceQuota | Namespace-level resource limits | CPU, memory, object count, and extended resource constraints |

Job does not express multi-role training, and Deployment does not understand that one model replica spans multiple nodes. Controllers such as Kubeflow Trainer, KubeRay, JobSet, and LeaderWorkerSet are used to fill in these semantics, not to replace Kubernetes.

## 3. Four Types of Extension Interfaces

### CRI: Container Runtime

The kubelet interacts with runtimes such as containerd and CRI-O through the Container Runtime Interface. GPU containers are ultimately still ordinary OCI containers, except that device nodes, driver libraries, and environment variables are additionally mounted at creation time.

Things to pay attention to:

- The compatibility relationship between containerd/CRI-O and Kubernetes;
- Device runtime configuration such as NVIDIA Container Toolkit and ROCm Runtime;
- The choice between the default Runtime and RuntimeClasses such as GPU and Kata;
- cgroup v2, shared memory, ulimit, and IPC configuration;
- The impact of image pulling, unpacking, and Snapshotter on cold start.

### CNI: Networking

CNI configures interfaces, addresses, and routes for Pods. AI clusters typically have multiple networks coexisting:

- The cluster default network, used for the Kubernetes API, Services, and ordinary east-west traffic;
- RDMA/InfiniBand/RoCE networks, used for training Collectives and KV Cache transfer;
- Public or ingress networks, used for inference APIs;
- Storage networks, used for datasets, models, and Checkpoints.

Multus can attach a second network interface to a Pod, but the actual performance, isolation, and NetworkPolicy capabilities are determined by the underlying CNI, SR-IOV, and hardware.

### CSI: Storage

CSI handles volume creation, mounting, expansion, and snapshots. AI platforms also frequently access object storage directly, so "having CSI" does not mean the data path is solved:

- Datasets may be read through S3/GCS/Azure Blob or parallel file systems;
- Model weights may come from Hugging Face, OCI Registry, or object storage;
- Checkpoints require concurrent writes, atomic commits, and recovery across failure domains;
- Local NVMe caching requires the scheduler to understand which node the data resides on.

### Device Plugin and DRA

Device Plugin exposes devices as integer extended resources, for example `nvidia.com/gpu: 1`. Dynamic Resource Allocation uses `DeviceClass`, `ResourceSlice`, and `ResourceClaim` to describe device attributes and allocation requirements.

Both are responsible only for device discovery and allocation. They are not responsible for installing kernel drivers, nor for quota and queuing of training jobs.

## 4. Controllers and Operators

Controllers continuously compare the desired state with the actual state and drive the system toward convergence through Reconcile. For example, a training controller may:

1. Observe a new TrainJob;
2. Create Workers, Launchers, or other roles;
3. Inject Rendezvous, environment variables, and ports;
4. Monitor Pod status;
5. Write failure reasons and completion status back to the CR;
6. Clean up or retry according to policy.

Operators are also often responsible for installing, upgrading, and configuring a software stack. For example, the GPU Operator manages drivers, the Toolkit, Device Plugin, MIG, and monitoring components.

Do not cram all platform logic into a single self-developed CRD. Prioritize reusing upstream APIs with single responsibilities and clear status semantics, and compose them through templates or platform APIs.

## 5. Three Different Scheduling Decisions

AI platforms have at least three decisions that are easily confused:

| Stage | Decision | Common Components |
| --- | --- | --- |
| Workload admission | Whether there is quota to run the entire job now | Kueue, Volcano Queue |
| Pod placement | Which node each Pod goes to | kube-scheduler, Volcano Scheduler |
| Request routing | Which model replica an inference request enters | Gateway, Inference Extension, llm-d Router |

In addition, the cluster autoscaler decides whether to create nodes based on Pending Pods, while Device Plugin/DRA decides which device to allocate within the scope of a node.

## 6. How Resource Requests Affect AI

The schedulability of a Pod is determined jointly by the resource requests of all its containers. Filling in only GPU while ignoring CPU and memory creates two problems:

- The scheduler may place too many data loaders or Tokenizers on the same node;
- The cluster autoscaler cannot accurately select instance specifications.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-worker
spec:
  restartPolicy: Never
  containers:
    - name: worker
      image: registry.example.com/ai/runtime@sha256:replace-with-digest
      resources:
        requests:
          cpu: "8"
          memory: 64Gi
          nvidia.com/gpu: "1"
        limits:
          cpu: "8"
          memory: 64Gi
          nvidia.com/gpu: "1"
```

Production environments must also consider `/dev/shm`, ephemeral storage, HugePages, locked memory, and PID limits. These do not automatically receive reasonable defaults just because a GPU is requested.

## 7. Pod Lifecycle and AI Semantics

Kubernetes only knows container exit codes, probes, and restart policies. It does not know:

- Whether Loss has become NaN;
- Whether all Ranks are still in the same Collective;
- Whether the Checkpoint is complete;
- Whether the model has been loaded into GPU memory;
- Whether the inference engine can still meet TTFT.

These health signals must be supplemented by frameworks, controllers, and business probes. The `Ready` of an inference Pod should indicate that it can accept requests for the target model, not merely that the process port is listening.

## 8. Namespace Is Not a Complete Isolation Boundary

Namespaces are suitable for organizing resources, RBAC, quotas, and policies, but multiple Pods still share the node kernel and device drivers. When running untrusted Notebooks, external training code, or Agent tools, you need to combine:

- Least-privilege ServiceAccounts;
- Pod Security Admission;
- Default-deny NetworkPolicies;
- Seccomp, AppArmor/SELinux;
- gVisor, Kata, or confidential containers;
- Dedicated node pools or dedicated clusters.

GPU Time-Slicing is also not GPU memory or fault isolation. Platforms must accurately describe the security guarantees of different sharing modes.

## 9. Minimal Troubleshooting Order

### Pod Stuck in Pending

```bash
kubectl get pod -A --field-selector=status.phase=Pending
kubectl describe pod -n <namespace> <pod>
kubectl get events -n <namespace> --sort-by=.lastTimestamp
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu
```

Judge in sequence: whether the queue has admitted it, whether resources exist, whether node constraints conflict, whether the PVC is bound, and whether autoscaling has failed.

### Container Started but GPU Not Visible

```bash
kubectl describe pod -n <namespace> <pod>
kubectl get runtimeclass
kubectl get daemonset -A
kubectl logs -n <operator-namespace> <device-plugin-pod>
```

Check the requested resource name, Device Plugin/DRA Driver, RuntimeClass, container image, and host driver.

### GPU Exists but Performance Is Poor

First break the problem into six layers—data, CPU, GPU kernel, inter-GPU communication, inter-node networking, and storage—then benchmark each separately. Do not mask the bottleneck by simply adding more GPUs.

## 10. Infrastructure Acceptance Checklist

- [ ] Can draw the complete control path from the user API to containers and devices.
- [ ] The owners and versions of CRI, CNI, CSI, Device Plugin/DRA are clear.
- [ ] Every AI Pod declares real CPU, memory, ephemeral storage, and device requests.
- [ ] Queue admission, Pod scheduling, node autoscaling, and request routing are each observable.
- [ ] Probes express model or training semantics, not just port checks.
- [ ] The isolation guarantees of Namespaces, nodes, and RuntimeClasses are written into platform documentation.
- [ ] Key events can be correlated to Workload, Job, Pod, Node, and Device.
- [ ] There are troubleshooting paths for Pending, invisible devices, and performance degradation.

## Further Reading

- [Kubernetes Components](https://kubernetes.io/docs/concepts/overview/components/)
- [Kubernetes Controllers](https://kubernetes.io/docs/concepts/architecture/controller/)
- [Container Runtime Interface](https://kubernetes.io/docs/concepts/architecture/cri/)
- [Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
- [Dynamic Resource Allocation](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)
- [RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
