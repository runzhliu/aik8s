# Image Plan and Sources

| Image | Purpose | Evidence and Nature |
| --- | --- | --- |
| scheduling-path.png | Distinguish queuing, serial decision-making, concurrent binding, and node execution | Kubernetes Scheduling Framework; simplified flow, omitting some extension points, not a performance chart |
| search-and-quality.png | Explain feasible node thresholds and sparse candidates | Kubernetes Scheduler Performance Tuning; 10000 / 1000 / 30 are hypothetical examples from the text |

Uses the MiniMax M3 font with a blue-orange color scheme, 1200×675. The source code is at `scripts/generate_large_scale_kubernetes_visuals.py`, and the image hash is recorded in `visual-manifest.json` of the adjacent monitoring topic.

References:

- [Scheduling Framework](https://v1-34.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)
- [Scheduler Performance Tuning](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduler-perf-tuning/)
