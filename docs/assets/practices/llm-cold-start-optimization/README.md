# LLM cold-start optimization figures

The figures visualize the cold-start stages, the measured local storage A/B,
and the optimization ladder documented in
`docs/ai-k8s/practices/llm-cold-start-optimization.md`.

Regenerate them with:

```bash
.venv/wechat/bin/python scripts/generate_llm_cold_start_figures.py \
  --output-dir docs/assets/practices/llm-cold-start-optimization
```

The root-disk and NVMe test used two nodes with the same GPU specification.
Only the framework-reported weight loading stage should be interpreted as the
storage comparison; the nodes had different local JIT and CUDA Graph cache
states.
