# Hy4-preview BF16 / 2×8 H20 formal result set

This directory contains the public-safe aggregate and correctness evidence used
by the Hy4-preview SGLang/vLLM report dated 2026-09-01. Per-request raw JSON and
runtime compiler caches remain in the execution archive; they are intentionally
excluded from the public repository because generated response bodies and JIT
artifacts add substantial noise without changing the published aggregates.

## Formal SGLang inputs

- Aggregate: `sglang-rdma-summary.csv` and `sglang-rdma-summary.md`
- Smoke: `sglang-rdma-smoke.json`
- Startup/RDMA evidence: `sglang-rdma-startup-evidence.txt` and
  `sglang-rdma-live-gpu.txt`
- One C1 run was polluted by an OpenWebUI request. The aggregate excludes it and
  uses a clean replacement run; both remain in the private execution archive.

## Formal vLLM inputs

- Aggregate: `vllm-rdma-summary.csv` and `vllm-rdma-summary.md`
- Smoke: `vllm-rdma-smoke.json`
- Startup/RDMA evidence: `vllm-rdma-startup-evidence.txt`

The baseline, RAG, and decode matrix used this development image's default
Prefix Cache setting (enabled). Random requests and median-of-run reporting reduce
fixed-prompt warm-cache bias, but do not prove a zero hit rate. The public report
therefore treats those results as a production-recipe comparison, not a strict
same-cache-state engine microbenchmark. SGLang still leads those cases, so any
vLLM cache benefit makes that directional conclusion conservative.

The formal vLLM long-context run explicitly used
`--no-enable-prefix-caching`, new seeds, and `--num-warmups 0` after the service
had already completed a full warm benchmark matrix. All first-shape effects remain
in the recorded results.

## Diagnostic-only vLLM inputs retained outside the public repository

- The first vLLM long-context JSON files were generated while this vLLM dev
  image still had its default Prefix Cache enabled. They are excluded from the
  formal aggregate.
- `vllm-rdma/vllm-cold-long/` changed the seeds and removed client warmups, but
  runtime metrics still observed shared-prefix cache hits. The run was stopped and
  is excluded. The execution archive records the observation and stop reason.

Each engine contributes 3,364 formal successful requests and zero failed requests.
The two-engine total is 6,728 successful requests.

## Long-context correctness

- `sglang-correctness.log`: 32K/64K/126K at 10%/50%/90% Needle depth,
  9/9 passed, followed by a three-tool multi-turn Agent flow that passed.
- `vllm-correctness.log`: the same request construction and gates, 9/9 Needle
  cases and the Agent flow passed.
- Service-reported `usage.prompt_tokens`, rather than a client-side tokenizer
  estimate, was used to calibrate context length.
- The runtime capacity reported at boot was 233,920 total tokens for SGLang and
  193,152 KV-cache tokens for vLLM. Both are below the model's 1,048,576-token
  context claim, so 1M was recorded as a failed capacity gate rather than sent as
  a request that the serving configuration could not admit.
