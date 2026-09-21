# Jev Decision Gateway Demo

这个 Demo 用同一批中英文客服工单比较三条窄决策路径：

- `rules`：关键词规则基线；
- `hf-community`：Hugging Face 上的 `pngwn/system-one-qwen3.5-4b-scorer` 社区模型；
- `laya-community`：Apache-2.0 的 Laya 开源 System One 模型，通过其公开 CPU Space 实测；
- `official`：TypeSafe 官方 `jev-1.13.0` API。

社区模型与官方 Jev 没有权重或训练方法上的继承关系。它只能验证“固定候选项、一次评分、概率门禁”这种工程形态，不能代替官方 Jev 的性能结论。

## 运行

```bash
cd examples/jev-decision-gateway

python3 demo.py \
  --provider rules \
  --output results/rules.json

python3 demo.py \
  --provider hf-community \
  --output results/hf-community.json

python3 demo.py \
  --provider laya-community \
  --output results/laya-community.json

TYPESAFE_API_KEY=... python3 demo.py \
  --provider official \
  --model jev-1.13.0 \
  --output results/official-jev-1.13.0.json
```

脚本只依赖 Python 标准库和 `curl`。官方模式不会打印 API Key。输入样本为公开仓库内的合成数据，不包含企业工单。

## 结果口径

报告会保留逐条预测、完整路由概率、紧急概率、语言标签与端到端延迟，并汇总：

- 路由准确率与紧急判断准确率；
- 多分类 Brier Score、二分类 Brier Score；
- 10 桶 Expected Calibration Error；
- P50、P95 和最大延迟；
- 中文与英文分层准确率；
- 不同置信度阈值下的覆盖率与选择性准确率。

20 条合成样本只能证明调用链和评估代码工作正常，不能作为生产模型排行。正式评估应替换为按时间切分、经领域人员复核的脱敏数据，并单独维护边界、分布外和对抗测试集。

## 本仓库保留的实测结果

`results/` 保留 2026-09-21 的逐条原始结果。规则基线完成 20/20，路由准确率 95%；Laya 完成 20/20，路由准确率 60%、紧急判断准确率 90%，模型侧 P50/P95 为 227/438 ms。Qwen3.5-4B Scorer 的匿名 ZeroGPU 配额在完成两条请求后耗尽，因此对应文件仍保留 20 条原始分母和 18 条错误，不计算正式准确率。

这组样本含有明显关键词，规则基线的高分只能说明测试管道正常。Laya 的公网端到端 P50/P95 为 3.82/6.50 秒，其中包含免费 Space 排队和网络时间，不能写成模型推理延迟。

## 如何接进 Agent

业务先执行确定性权限和风险规则，再把需要语言理解的窄问题交给决策模型。模型只返回建议，Decision Gateway 根据离线校准得到的阈值决定自动路由、调用更强模型或转人工。删除、转账、发布等高风险动作始终保留确定性审批，不允许概率结果越权。
