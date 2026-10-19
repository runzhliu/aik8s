# NVCRE diagrams and standalone NCCL/DCGM evidence

The article combines NVCRE v0.7.0 source analysis with standalone readiness tests on two nodes and 16 H20-3e GPUs. Tests used ordinary Kubernetes Jobs. NVCRE, Trainer, and JobSet were not deployed, and Certification was not executed.

| File | Evidence and production method |
| --- | --- |
| `execution-chain.png` | Deterministic diagram of NVCRE v0.7.0 execution, measurements, and results |
| `production-lifecycle.png` | Recommended integration with node onboarding, changes, and retests; not an executed production-admission workflow |
| `validation-scope.png` | Recommended staged validation, not measured scores |
| `result-retention.png` | Deterministic diagram of measurement freezing, Gauge cleanup, and report retention |
| `roce-tcp-comparison.png` | Two-node AllReduce from the sanitized CSV; three-round medians and logarithmic axes |
| `gpu-nccl-observation.png` | Actual communication-phase utilization panel; eight-GPU average per node |
| `gpu-nccl-power.png` | Actual communication-phase power panel; highest GPU per node |
| `gpu-dcgm-observation.png` | Actual GPU-memory panel during repaired diagnostics; highest GPU per node |
| `gpu-dcgm-temperature.png` | Actual temperature panel during repaired diagnostics; highest GPU per node |
| `nccl-results-dashboard.png` | Actual diagnostic table retaining initial failures, repaired passes, and timeouts |
| `nccl-measurements.csv` | 30 successful communication rounds × 10 message sizes; Out-of-place readings; Node B uses separate additional attempt 2 |
| `experiment-summary.json` | Parameters, repeats, diagnostic states, fixed intervals, and sampling definitions |
| `evidence/` | Five sanitized original panel screenshots, plus titles, source hashes, and layout metadata |

Generation code:

- Diagrams and two covers: `scripts/generate_nvcre_article_assets.py`.
- Data curves and evidence framing: `scripts/generate_nvcre_benchmark_assets.py`.

Article figures follow MiniMax M3's 1200×675 format, Hiragino Sans GB / Helvetica Neue fonts, and light layout. Actual screenshots are panel crops, scaled proportionally with explanations outside the evidence. Curves and values are unchanged. WeChat and public documentation use the same figures.

Metrics came from an independent experiment Prometheus/Grafana. Prometheus scraped every 5 seconds; the existing DCGM Exporter refreshed devices every 30 seconds. Sampling peaks are not instantaneous peaks of short workloads. Communication result metrics were exported from saved NCCL output, not NVCRE's `nvcre_*` metrics.

There were 39 communication execution attempts. Of the first 30, nine Node B checks failed because of executor preparation. Nine additional independent attempts followed, producing 30 successful rounds with zero numerical errors. Original parsing errors for AllToAll's `N/A` and one truncated terminal output were corrected from saved node files without rerunning tests to overwrite scores.

Initial diagnostics failed because CUDA 13 plugins were absent. After adding the matching official package, Level 1 Software passed on eight GPUs per node. Both Level 2 runs timed out at 730 seconds without complete diagnostic results. Raw diagnostic JSON contains device serial numbers, so public artifacts retain only sanitized summaries. `status_field_counts` includes GPU and summary status fields, not a count of test cases.

Figures and data exclude internal cluster names, IPs, serial numbers, business identifiers, credentials, and private registries. Internal logs, deployment packages, plans, and code remain in locally ignored directories.
