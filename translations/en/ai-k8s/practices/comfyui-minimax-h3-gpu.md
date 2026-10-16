---
title: "Deploying ComfyUI on Kubernetes: Offline Images, CephFS Models, and Cross-Cluster Ingress"
description: "Using NVIDIA GPUs, read-only CephFS, ComfyUI extra_model_paths, Init Container model aliases, and two-tier Ingress to serve a MiniMax-H3 workflow page in a network-restricted Kubernetes environment"
status: lab
last_reviewed: 2026-08-08
---

# Deploying ComfyUI on Kubernetes: Offline Images, CephFS Models, and Cross-Cluster Ingress

This experiment deploys ComfyUI to a Kubernetes cluster with NVIDIA GPUs but without stable access to GitHub. Model weights already reside on shared CephFS, and the office network can only reach the Ingress of another Kubernetes cluster, so we also need to solve model directory mapping, workflow filename compatibility, and cross-cluster ingress proxying.

Final result: the ComfyUI Pod and page are usable; MiniMax-H3 quantized weights, Text Encoder, and VAE are discovered through read-only CephFS; lowercase model names referenced by the workflow are resolved via Init Container aliases; the office network can reach the page through the other cluster's Ingress. MiniMax-H3 final video generation still lacks a complete successful sample, and this article will not describe "page accessible, models selectable" as "the video pipeline is fully working."

!!! warning "Public documentation has been sanitized"
    This article does not record internal cluster names, nodes, Registry, Ceph Monitors, real model volume paths, Ingress domains, IPs, or Secrets. Environment-related values uniformly use the `<...>` placeholder.

## 1. Experiment Topology

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

| Item | Value Used in Testing |
| --- | --- |
| GPU | NVIDIA L20, 1 card requested per Pod |
| ComfyUI port | 8188 |
| Model storage | CephFS, mounted read-only |
| Deployment strategy | `Recreate`, avoiding rolling updates that would temporarily occupy two GPUs |
| Model discovery | `extra_model_paths.yaml` |
| Filename compatibility | Init Container + `emptyDir` symlinks |
| External entry | Target Ingress + cross-cluster Ingress proxy |

## 2. Offline Environments Must Bake the Runtime into the Image

Production Pods cannot access GitHub after startup, so you cannot rely on container startup scripts to temporarily run `git clone`, ComfyUI Manager online installation, or dynamic downloads of frontend and Custom Nodes. The image should at minimum include:

- ComfyUI code at a pinned commit;
- Python, PyTorch, CUDA Runtime, and ComfyUI Python dependencies;
- Required Custom Nodes with confirmed licenses and versions;
- Frontend static assets;
- An Entrypoint that starts without accessing external networks.

The AMD64 CUDA image used here is approximately 6.5 GB, and the first node pull takes about 80 seconds. When building for older Registries or image sync systems, explicitly output a single-architecture legacy Manifest to avoid the default OCI Index and Attestation being misjudged by older Jobservice:

```bash
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --output=type=docker \
  -t <STAGING_REGISTRY>/<PROJECT>/comfyui:<TAG> .
```

After vulnerability scanning, SBOM archival, and internal Registry synchronization, the production Deployment references only immutable Tags or Digests. Do not write Registry passwords, Hugging Face Tokens, or Ceph Keys into public documentation or image layers.

## 3. Single-GPU Deployment

The core Deployment can be simplified to:

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

`startupProbe` provides a window of up to 30 minutes to cover the first image pull, ComfyUI startup, and model directory scanning; it does not let an unready Pod receive traffic early. The model volume remains read-only at both the Volume and VolumeMount layers.

## 4. ComfyUI Does Not Automatically Treat Arbitrary Directories as Models

The shared model directory contains the following types of MiniMax-H3 files:

```text
MiniMax_H3_FL2VA_pruned_int4_convrot.safetensors
MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors
MiniMax_H3_FL2VA_pruned_mixed_int4_int8_convrot.safetensors
MiniMax_H3_Ref2VA_pruned_int8_convrot.safetensors
text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors
vae/minimax_h3_audio_vae_fp32.safetensors
vae/minimax_h3_video_vae_fp16.safetensors
```

Simply mounting the parent directory to `/models` is not enough. ComfyUI Loaders look up files by categories such as `diffusion_models`, `text_encoders`, and `vae`, so explicit mapping is required:

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

After modifying the ConfigMap, the Pod must be recreated for ComfyUI to re-read the model paths. Updating only the ConfigMap without restarting may leave the dropdown lists in the browser showing stale values.

## 5. "Weights Are Mounted but the Workflow Still Reports Missing Files"

The imported workflow references:

```text
minimax_h3_fl2va_pruned_int8_convrot.safetensors
```

But the actual filenames are:

```text
MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors
```

Linux filenames are case-sensitive, and ComfyUI workflows also save the logical filename of the model, so "the file really exists" does not mean the workflow reference can match. The model volume is a shared read-only directory and cannot be renamed directly. The safe approach is to create aliases in a temporary `emptyDir`:

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

After the fix, you can confirm from inside the Pod that the ComfyUI API has enumerated the target files:

```bash
curl -s http://127.0.0.1:8188/object_info \
  | grep -F 'minimax_h3_fl2va_pruned_int8_convrot.safetensors'
```

This check succeeded in this experiment. It proves the Loader has discovered the models, but it does not yet prove the workflow can generate video.

When the workflow UI also reports "missing input," check whether `Load Image` or media input nodes already have files uploaded. This is a separate issue from model weights; adding model aliases will not automatically generate input images.

## 6. Minimal Acceptance Checklist for the Workflow

After importing a JSON workflow provided by someone else, at minimum check each of the following:

1. Whether all node types exist; do not rely on the production Pod to install missing Custom Nodes online;
2. Whether the logical filenames of the Diffusion Model, Text Encoder, and Video/Audio VAE match;
3. Whether input images, audio, or first/last frames have been uploaded;
4. Whether node input and output types match the current Custom Node versions;
5. Whether width, height, frame count, FPS, and sampling steps fit within single-GPU memory;
6. Whether the output directory has persistence requirements; do not default to relying on the container root filesystem;
7. After a page refresh or Pod recreation, whether `object_info` still contains all models.

MiniMax-H3 is typically not something you can complete with "one main weight + one prompt" to produce video. A complete workflow may simultaneously depend on Diffusion weights, a Qwen3-VL Text Encoder, Video VAE, Audio VAE, input images, and model-specific Custom Nodes.

## 7. Forwarding Through Another Cluster's Ingress

The target GPU cluster's Ingress is unreachable from the office network, while another cluster's Ingress address is reachable. The experiment uses two-tier Host routing:

```text
浏览器请求 Host: <OFFICE_COMFYUI_HOST>
  → 代理集群 Ingress
  → Selectorless Service
  → 手工 Endpoints：目标 GPU 集群 Ingress Controller IP
  → 改写 Upstream Host: <TARGET_COMFYUI_HOST>
  → 目标集群 Ingress
  → ComfyUI Service
```

The proxy cluster creates a Selector-less Service and Endpoints:

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

Then uses an Ingress with longer timeouts, upload size limits, and the target Host:

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

`upstream-vhost` is critical. The Endpoints point to the target Ingress Controller, not the ComfyUI Pod; if the office network Host is still carried during forwarding, the target Ingress cannot find a matching Rule and may return a default backend or 404.

This approach is suitable for experiments but has clear production boundaries: Endpoints IP changes are not automatically updated; the link depends on two Ingresses; WebSocket, long requests, upload limits, and cancellation propagation must be verified; the page also needs authentication, TLS, access auditing, and NetworkPolicy. For the long term, enterprise DNS, cross-cluster Service Discovery, Gateway API, multi-cluster networking, or a managed reverse proxy are better options.

## 8. Results of This Round and Outstanding Items

Completed:

- ComfyUI runs stably on one GPU, with Startup and Readiness Probes passing;
- The approximately 6.5 GB offline image runs without runtime access to GitHub;
- The CephFS model directory remains read-only;
- `extra_model_paths` can discover the Diffusion Model, Text Encoder, and VAE;
- The Init Container can create temporary model aliases for workflows with case mismatches;
- The ComfyUI `/object_info` has returned the target model names referenced by the workflow;
- Office network requests can be forwarded through the other cluster's Ingress to the GPU cluster's ComfyUI.

Not yet completed:

- An end-to-end successful sample of MiniMax-H3 from input image and Prompt to video file;
- A full compatibility matrix of Custom Nodes, model versions, and workflow JSON;
- Output file persistence, quotas, and lifecycle cleanup;
- Multi-user authentication, isolation, auditing, and GPU task queues;
- Automatic Ingress Endpoints discovery and failover.

For pure API inference or batch video generation, ComfyUI is better suited as a workflow validation and visualization tool; production services should still consider dedicated inference APIs, asynchronous queues, object storage, task state machines, and observability.
