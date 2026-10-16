# Multi-cluster stability article illustrations

Both figures are architectural diagrams of the approach proposed in this article, not internal enterprise architecture or production test data.

| Figure | Purpose | Output |
| --- | --- | --- |
| fleet-boundaries | Shows the boundaries between central policy, group budgets, and cluster-local execution | 1200×675 desktop image, 720×1080 mobile image |
| rollout-gates | Shows staged rollout and stop conditions for a hypothetical 300-cluster fleet | 1200×675 desktop image, 720×1080 mobile image |

Source code: `scripts/generate_fleet_reliability_visuals.py`. Fonts and colors reuse the drawing helper functions from the Kubernetes flow-control article. Assume batches of 2, 8, 30, 60, 200, mutually non-overlapping, totaling 300; the final group is still executed in small batches. All figures are explicitly labeled "reference design" or "hypothetical example."
