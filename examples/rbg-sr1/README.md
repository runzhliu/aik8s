# RBG sr1 验证清单

该目录保存 sr1 集群的 RBG 安装参数和 CPU 多角色验证样例。样例中的
`gateway`、`prefill`、`decode` 都是 NGINX 占位进程，只用于验证 RBG 的控制面，
不包含推理引擎、模型权重或 KV Cache 传输。

```bash
helm upgrade --install rbgs \
  https://github.com/sgl-project/rbg/releases/download/v0.8.0-alpha.3/rbgs-0.8.0-alpha.3.tgz \
  --namespace rbgs-system \
  --create-namespace \
  -f examples/rbg-sr1/helm-values.yaml \
  --wait

kubectl apply -f examples/rbg-sr1/cpu-role-demo.yaml
kubectl get rbg,ri,rbgsa,pod,svc -n rbg-demo
```

生产部署应替换占位镜像，并根据实际方案接入 vLLM、SGLang、NVIDIA Dynamo、
Mooncake 或其他推理运行时。RBG 当前版本仍为 alpha，升级和回滚前应先验证 CRD
转换、Webhook、调度器集成与故障恢复。
