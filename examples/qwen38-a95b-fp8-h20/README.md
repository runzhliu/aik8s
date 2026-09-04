# Qwen3.8-2.4T-A95B-FP8 H20 测试材料

本目录用于 `Qwen/Qwen3.8-2.4T-A95B-FP8` 在 4 台 8×141GB H20 上的部署预检、
SGLang/vLLM 正确性测试、公平压测和长上下文验证。

完整 Gate、拓扑依据和停止条件见
[`docs/ai-k8s/practices/qwen38-a95b-fp8-h20-deployment-benchmark-plan.md`](../../docs/ai-k8s/practices/qwen38-a95b-fp8-h20-deployment-benchmark-plan.md)。

## 资源与路径

首轮固定使用 `TP8 × PP4`，总计 32 张 141GB H20。四台节点各自保存完整模型副本：

```text
host NVMe: /apps/dat/model-cache/Qwen3.8-2.4T-A95B-FP8/v1
container: /models-nvme/Qwen3.8-2.4T-A95B-FP8/v1
```

实际共享存储路径、四台节点和模型 Revision 在同步完成后填写；服务必须检查 NVMe 完成标记，
不得静默回退到共享存储。

## 文件

```text
preflight.py   # 零 GPU：配置、分片、Revision、运行时与 CLI 参数预检
smoke.py       # Reasoning、reasoning_effort、Tool Call、多轮与流式正确性
needle.py      # 32K/64K/128K/262K 及实验性 512K/1M 检索验证
cases.csv      # 公平性能与长上下文 Case
benchmark.sh   # 默认 dry-run；主对比统一使用 vllm bench serve
images/        # 固定上游 Manifest 与内网同步状态
```

## 预检

```bash
MODEL_PATH=/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1 \
ENGINE=sglang \
python3 preflight.py
```

## 功能 Smoke

```bash
BASE_URL=http://127.0.0.1:30000/v1 \
MODEL=qwen38-a95b-fp8 \
python3 smoke.py
```

## 公平压测

默认只打印命令：

```bash
ENGINE=sglang STAGE=baseline bash benchmark.sh
```

确认服务上限、客户端和输出目录后执行：

```bash
ENGINE=sglang \
STAGE=baseline \
EXECUTE=1 \
BASE_URL=http://127.0.0.1:30000 \
TOKENIZER=/models-nvme/Qwen3.8-2.4T-A95B-FP8/v1 \
MODEL=qwen38-a95b-fp8 \
MAX_CONTEXT=32768 \
RUN_LABEL=h20-fp8-tp8-pp4-target \
bash benchmark.sh
```

SGLang 完成并释放 32 卡后，vLLM 使用同一客户端、Cases 和参数复跑。
