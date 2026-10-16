# DeepSeek V4 Flash H20 evaluation figures

The figures are generated from the benchmark numbers recorded in
`docs/ai-k8s/practices/deepseek-v4-flash-h20-evaluation.md`.

Regenerate them with:

```bash
.venv/wechat/bin/python scripts/generate_deepseek_pd_figures.py \
  --output-dir docs/assets/practices/deepseek-v4-flash-h20-evaluation
```

The charts compare different GPU budgets. They visualize the measured latency and throughput trade-off and must not be interpreted as an equal-resource A/B test.
