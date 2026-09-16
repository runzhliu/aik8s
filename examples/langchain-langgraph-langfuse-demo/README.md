# LangChain × LangGraph × Langfuse Demo

这个示例把三层能力放进一次真实请求：

- LangChain：`ChatPromptTemplate`、`Runnable`、`StructuredTool` 和 `OutputParser`；
- LangGraph：共享 State、条件路由、节点转换和错误传播；
- Langfuse：Trace、Observation、工具耗时与错误记录。

Demo 提供正常、慢调用和工具失败三条稳定复现路径。内置模型接口是确定性 Runnable，不访问外部模型，因此适合先验证编排和可观测链路；替换为真实模型的方法见配套文档。

## 本地运行

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

export LANGFUSE_HOST=http://127.0.0.1:3000
export LANGFUSE_PUBLIC_KEY=REPLACE_WITH_PUBLIC_KEY
export LANGFUSE_SECRET_KEY=REPLACE_WITH_SECRET_KEY
export LANGFUSE_PROJECT_ID=langgraph-demo
python app.py
```

访问 <http://127.0.0.1:8080>。

## Kubernetes

先按 [Langfuse Kubernetes Helm 文档](https://langfuse.com/self-hosting/deployment/kubernetes-helm)部署 Langfuse。仓库里的 `langfuse-values.example.yaml` 是本次实验使用的 3.x 单副本拓扑示例，不代表生产高可用配置。

```bash
docker build -t REGISTRY/langgraph-langfuse-demo:v1 .
docker push REGISTRY/langgraph-langfuse-demo:v1

# 替换镜像和 Secret 占位符后执行
kubectl apply -f k8s/deployment.yaml
kubectl -n langgraph-observability rollout status deploy/langgraph-demo

kubectl -n langgraph-observability port-forward svc/langgraph-demo 18080:8080
kubectl -n langgraph-observability port-forward svc/langfuse-web 13000:3000
```

访问：

- Demo：<http://127.0.0.1:18080>
- Langfuse：<http://127.0.0.1:13000>

不要把填入真实密码和密钥后的 values、Secret 清单提交到仓库。
