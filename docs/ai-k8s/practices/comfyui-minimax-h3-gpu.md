---
title: 在 Kubernetes 部署 ComfyUI：离线镜像、CephFS 模型与跨集群 Ingress
description: 使用 NVIDIA GPU、只读 CephFS、ComfyUI extra_model_paths、Init Container 模型别名及双层 Ingress，在受限网络 Kubernetes 环境提供 MiniMax-H3 工作流页面
status: lab
last_reviewed: 2026-08-08
---

# 在 Kubernetes 部署 ComfyUI：离线镜像、CephFS 模型与跨集群 Ingress

本次实验把 ComfyUI 部署到一套有 NVIDIA GPU、但不能稳定访问 GitHub 的 Kubernetes 集群。模型权重已经位于共享 CephFS，办公网络只能访问另一套 Kubernetes 集群的 Ingress，因此还需要解决模型目录映射、工作流文件名兼容和跨集群入口代理。

最终结果：ComfyUI Pod 和页面可用；MiniMax-H3 量化权重、Text Encoder 和 VAE 通过只读 CephFS 被发现；工作流引用的小写模型名通过 Init Container 别名解决；办公网络可以经过另一集群的 Ingress 访问页面。MiniMax-H3 最终视频生成仍缺少完整成功样本，本文不会把“页面可访问、模型可选择”写成“视频链路已经跑通”。

!!! warning "公开文档已经脱敏"
    文中不会记录内部集群名、节点、Registry、Ceph Monitor、模型卷真实路径、Ingress 域名、IP 或 Secret。环境相关值统一使用 `<...>` 占位符。

## 1. 实验拓扑

```text
浏览器
  → 办公网可达集群的 Ingress
  → 无 Selector Service + 手工 Endpoints
  → GPU 集群的 Ingress Controller
  → GPU 集群目标 Ingress
  → ComfyUI Service :8188
  → ComfyUI Pod / 1×GPU
       ├── /models：只读 CephFS
       ├── /config：extra_model_paths ConfigMap
       └── /model-aliases：Init Container 生成的临时软链接
```

| 项目 | 实测选择 |
| --- | --- |
| GPU | NVIDIA L20，单 Pod 请求 1 卡 |
| ComfyUI 端口 | 8188 |
| 模型存储 | CephFS，只读挂载 |
| 部署策略 | `Recreate`，避免滚动更新暂时占两张 GPU |
| 模型发现 | `extra_model_paths.yaml` |
| 文件名兼容 | Init Container + `emptyDir` 软链接 |
| 外部入口 | 目标 Ingress + 跨集群 Ingress 代理 |

## 2. 离线环境必须把运行时做进镜像

生产 Pod 启动后无法访问 GitHub，就不能依赖容器启动脚本临时执行 `git clone`、ComfyUI Manager 在线安装或动态下载前端和 Custom Node。镜像至少应预置：

- 固定 Commit 的 ComfyUI 代码；
- Python、PyTorch、CUDA Runtime 和 ComfyUI Python 依赖；
- 已确认许可证与版本的必要 Custom Node；
- 前端静态资源；
- 不访问外网也能启动的 Entrypoint。

本次 AMD64 CUDA 镜像约 6.5 GB，节点首次拉取约 80 秒。面向较旧 Registry 或镜像同步系统构建时，显式输出单架构传统 Manifest，避免默认 OCI Index 和 Attestation 被旧 Jobservice 误判：

```bash
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --output=type=docker \
  -t <STAGING_REGISTRY>/<PROJECT>/comfyui:<TAG> .
```

完成漏洞扫描、SBOM 留档和内部 Registry 同步后，生产 Deployment 只引用不可变 Tag 或 Digest。不要在公开文档或镜像层中写入 Registry 密码、Hugging Face Token 或 Ceph Key。

## 3. 单卡 Deployment

核心 Deployment 可以简化为：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: comfyui-minimax-h3
spec:
  replicas: 1
  strategy:
    type: Recreate
  template:
    spec:
      containers:
        - name: comfyui
          image: <REGISTRY>/comfyui:<IMMUTABLE_TAG>
          env:
            - name: CLI_ARGS
              value: >-
                --listen 0.0.0.0
                --port 8188
                --lowvram
                --extra-model-paths-config /config/extra_model_paths.yaml
          ports:
            - name: http
              containerPort: 8188
          resources:
            requests:
              cpu: "8"
              memory: 32Gi
              nvidia.com/gpu: "1"
            limits:
              cpu: "32"
              memory: 256Gi
              nvidia.com/gpu: "1"
          startupProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 10
            failureThreshold: 180
          readinessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 10
            failureThreshold: 6
          volumeMounts:
            - name: model-corpus
              mountPath: /models
              readOnly: true
            - name: model-paths
              mountPath: /config
              readOnly: true
            - name: model-aliases
              mountPath: /model-aliases
              readOnly: true
      volumes:
        - name: model-corpus
          cephfs:
            monitors: [<CEPH_MONITOR_1>, <CEPH_MONITOR_2>, <CEPH_MONITOR_3>]
            path: <READ_ONLY_MODEL_ROOT>
            readOnly: true
            secretRef:
              name: <CEPH_SECRET>
            user: <CEPH_USER>
        - name: model-paths
          configMap:
            name: comfyui-minimax-h3-model-paths
        - name: model-aliases
          emptyDir: {}
```

`startupProbe` 给了最长 30 分钟窗口，是为了覆盖首次镜像拉取、ComfyUI 启动和模型目录扫描；它不会让未就绪 Pod 提前接流量。模型卷在 Volume 与 VolumeMount 两层都保持只读。

## 4. ComfyUI 不会把任意目录自动当成模型

共享模型目录包含以下类型的 MiniMax-H3 文件：

```text
MiniMax_H3_FL2VA_pruned_int4_convrot.safetensors
MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors
MiniMax_H3_FL2VA_pruned_mixed_int4_int8_convrot.safetensors
MiniMax_H3_Ref2VA_pruned_int8_convrot.safetensors
text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors
vae/minimax_h3_audio_vae_fp32.safetensors
vae/minimax_h3_video_vae_fp16.safetensors
```

仅把父目录挂载到 `/models` 不够。ComfyUI Loader 按 `diffusion_models`、`text_encoders`、`vae` 等类别查找文件，需要显式映射：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: comfyui-minimax-h3-model-paths
data:
  extra_model_paths.yaml: |
    minimax_h3:
      base_path: /models/<MINIMAX_H3_QUANTIZED_DIR>
      diffusion_models: .
      text_encoders: text_encoders
      audio_encoders: audio_encoders
      vae: vae
    workflow_aliases:
      base_path: /model-aliases
      diffusion_models: diffusion_models
```

修改 ConfigMap 后需要重建 Pod，ComfyUI 才会重新读取模型路径。只更新 ConfigMap 而不重启，浏览器中的下拉列表可能仍是旧值。

## 5. “挂载了权重但工作流仍提示缺失”

导入的工作流引用：

```text
minimax_h3_fl2va_pruned_int8_convrot.safetensors
```

实际文件名却是：

```text
MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors
```

Linux 文件名区分大小写，ComfyUI 工作流还会保存模型的逻辑文件名，所以“文件真实存在”不代表工作流引用能匹配。模型卷是共享只读目录，不能直接重命名。安全做法是在临时 `emptyDir` 中创建别名：

```yaml
initContainers:
  - name: create-model-aliases
    image: <REGISTRY>/busybox:<TAG>
    command: [sh, -c]
    args:
      - |
        set -eu
        mkdir -p /model-aliases/diffusion_models
        for file in /models/<MINIMAX_H3_QUANTIZED_DIR>/MiniMax_H3_*.safetensors; do
          base=${file##*/}
          lower=$(echo "$base" | tr '[:upper:]' '[:lower:]')
          ln -sf "$file" "/model-aliases/diffusion_models/$lower"
        done
    volumeMounts:
      - name: model-corpus
        mountPath: /models
        readOnly: true
      - name: model-aliases
        mountPath: /model-aliases
```

修复后可以从 Pod 内确认 ComfyUI API 已枚举目标文件：

```bash
curl -s http://127.0.0.1:8188/object_info \
  | grep -F 'minimax_h3_fl2va_pruned_int8_convrot.safetensors'
```

本次该检查成功。它证明 Loader 已发现模型，但还不证明工作流可以生成视频。

工作流界面同时提示“缺少输入”时，应检查 `Load Image` 或媒体输入节点是否已经上传文件。这与模型权重是两个独立问题；补齐模型别名不会自动生成输入图片。

## 6. 工作流的最小验收清单

导入别人提供的 JSON 工作流后，至少逐项检查：

1. 所有节点类型是否存在，缺失 Custom Node 时不要依赖生产 Pod 在线安装；
2. Diffusion Model、Text Encoder、Video/Audio VAE 的逻辑文件名是否匹配；
3. 输入图片、音频或首尾帧是否已上传；
4. 节点输入输出类型是否与当前 Custom Node 版本一致；
5. 宽高、帧数、FPS 和采样步数是否适合单卡显存；
6. 输出目录是否有持久化需求，不能默认依赖容器根文件系统；
7. 页面刷新或 Pod 重建后，`object_info` 是否仍包含全部模型。

MiniMax-H3 通常不是“一个主权重 + 一句 Prompt”就能完成视频。一个完整工作流可能同时依赖 Diffusion 权重、Qwen3-VL Text Encoder、Video VAE、Audio VAE、输入图片和模型专用 Custom Node。

## 7. 通过另一集群的 Ingress 转发

目标 GPU 集群的 Ingress 在办公网络不可达，而另一套集群的 Ingress 地址可达。实验采用两层 Host 路由：

```text
浏览器请求 Host: <OFFICE_COMFYUI_HOST>
  → 代理集群 Ingress
  → Selectorless Service
  → 手工 Endpoints：目标 GPU 集群 Ingress Controller IP
  → 改写 Upstream Host: <TARGET_COMFYUI_HOST>
  → 目标集群 Ingress
  → ComfyUI Service
```

代理集群创建无 Selector Service 和 Endpoints：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: comfyui-cross-cluster-proxy
spec:
  ports:
    - name: http
      port: 80
      targetPort: 80
---
apiVersion: v1
kind: Endpoints
metadata:
  name: comfyui-cross-cluster-proxy
subsets:
  - addresses:
      - ip: <TARGET_INGRESS_IP_1>
      - ip: <TARGET_INGRESS_IP_2>
    ports:
      - name: http
        port: 80
```

再用 Ingress 设置较长超时、上传大小和目标 Host：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: comfyui-cross-cluster
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: HTTP
    nginx.ingress.kubernetes.io/proxy-body-size: 2g
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/upstream-vhost: <TARGET_COMFYUI_HOST>
spec:
  ingressClassName: nginx
  rules:
    - host: <OFFICE_COMFYUI_HOST>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: comfyui-cross-cluster-proxy
                port:
                  name: http
```

`upstream-vhost` 很关键。Endpoints 指向的是目标 Ingress Controller，而不是 ComfyUI Pod；如果转发时仍携带办公网 Host，目标 Ingress 找不到对应 Rule，可能返回默认后端或 404。

该方式适合实验，但有明显生产边界：Endpoints IP 变化不会自动更新；链路依赖两套 Ingress；必须验证 WebSocket、长请求、上传限制和取消传播；页面还需要认证、TLS、访问审计与 NetworkPolicy。长期方案更适合使用企业 DNS、跨集群 Service Discovery、Gateway API、多集群网络或受管反向代理。

## 8. 本轮结果与未完成项

已经完成：

- ComfyUI 使用一张 GPU 稳定运行，Startup 与 Readiness Probe 正常；
- 约 6.5 GB 的离线镜像无需运行时访问 GitHub；
- CephFS 模型目录保持只读；
- `extra_model_paths` 能发现 Diffusion Model、Text Encoder 和 VAE；
- Init Container 能为大小写不一致的工作流创建临时模型别名；
- ComfyUI `/object_info` 已返回工作流引用的目标模型名；
- 办公网请求可以经过另一集群 Ingress 转发到 GPU 集群 ComfyUI。

尚未完成：

- MiniMax-H3 从输入图片、Prompt 到视频文件的端到端成功样本；
- 自定义节点、模型版本与工作流 JSON 的完整兼容矩阵；
- 输出文件持久化、配额和生命周期清理；
- 多用户鉴权、隔离、审计和 GPU 任务队列；
- Ingress Endpoints 自动发现与故障切换。

对于纯 API 推理或批量视频生成，ComfyUI 更适合作为工作流验证和可视化工具；生产服务仍应考虑专用推理 API、异步队列、对象存储、任务状态机和可观测性。
