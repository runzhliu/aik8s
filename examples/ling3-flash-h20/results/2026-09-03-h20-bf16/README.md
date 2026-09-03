# Ling-3.0-flash BF16 / 4×H20 formal result set

This directory contains the public-safe aggregate and correctness evidence used
by the Ling-3.0-flash SGLang/vLLM report dated 2026-09-03. Per-request raw JSON,
runtime logs, generated responses, and compiler caches remain outside the public
repository. Internal addresses, registry names, mount paths, and credentials are
not included.

## Formal inputs

| Configuration | Aggregate | Successful requests | Failed requests |
| --- | --- | ---: | ---: |
| SGLang baseline, speculative off | `sglang-baseline-summary.csv` / `.md` | 2,411 | 0 |
| SGLang NEXTN | `sglang-nextn-summary.csv` / `.md` | 2,100 | 0 |
| vLLM baseline, speculative off | `vllm-baseline-summary.csv` / `.md` | 2,411 | 0 |
| vLLM MTP | `vllm-mtp-summary.csv` / `.md` | 2,100 | 0 |

The four formal configurations contain 9,022 successful requests and zero
failed requests. The baseline matrix contains 41 benchmark JSON files per
engine; each speculative A/B set contains 24. Except for the single-run 256K
capability probe, performance cases use three repetitions and publish the median
of each run-level metric.

Both runtimes kept prefix caching enabled but successfully reset the cache before
every formal benchmark repetition. The same client, case definitions, input and
output lengths, seeds, request rate, and repeat counts were used for both engines.

The serving images were pinned to the linux/amd64 manifests
`lmsysorg/sglang@sha256:687b721a23126f33aada6e065d101fe1fd35f1e42b44e6dfcc0bdc481a4891f2`
and
`vllm/vllm-openai@sha256:38226e33915718dc7b5fc3d114e64b1dfff28e9bf1de97f9f1094e8ef558183b`.

## Correctness evidence

- `sglang-smoke.json` and `vllm-smoke.json`: model discovery, thinking on/off,
  streaming, multi-turn chat, and structured tool calling all passed.
- `sglang-needle.jsonl` and `vllm-needle.jsonl`: 32K, 64K, 128K, and 256K at
  10%, 50%, and 90% Needle depth; each engine passed 12/12 cases.
- Needle elapsed time is execution evidence only. It is not used for the runtime
  performance ranking because those cases ran sequentially and did not have the
  same controlled state as the benchmark matrix.

## Excluded diagnostic attempts

The following attempts are intentionally excluded from all aggregates and charts:

- an older vLLM image that did not natively recognize
  `BailingMoeV3ForCausalLM`;
- nightly vLLM startup attempts where Custom All-Reduce failed to initialize on
  this H20 environment;
- an early cache-reset job where the endpoint was unavailable and no formal
  performance JSON was produced.

The formal vLLM service used a pinned nightly build, disabled Custom All-Reduce,
enabled the development cache-reset endpoint, and verified a successful reset
before the benchmark jobs were accepted.

## Rebuild charts

From the repository root:

```bash
python3 examples/ling3-flash-h20/make_report_charts.py
```

The script reads only the public aggregate/correctness files in this directory
and deterministically writes the SVG assets used by the report.
