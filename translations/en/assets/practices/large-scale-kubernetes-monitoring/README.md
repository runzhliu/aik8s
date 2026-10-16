# Figure Plan and Sources

Use the project's existing MiniMax M3 chart font, blue-orange color scheme, and 1200×675 canvas size. Generation source: `scripts/generate_large_scale_kubernetes_visuals.py`.

| Image | Purpose | Source and Nature |
| --- | --- | --- |
| local-and-central.png | Explains the responsibilities of local alerting and central storage | Conceptual architecture designed by the author, based on Prometheus Agent, Remote Write, and vmagent documentation; not an experimental topology screenshot |
| selection-path.png | Compares the requirements of the four selection options | Visual index of the solution comparison in the main text; not a performance ranking |
| resource-count-evidence.png | Verifies query and object trends after deployment | Excerpt from the actual Grafana Kubernetes Views Global dashboard, Kubernetes 1.30.4, 12 nodes, 30-second collection interval |

The screenshot retains only the object count panel; curves and numbers are unmodified. Internal identifiers and the capacity panel whose measurement criteria are not yet aligned have been cropped out. Original screenshots and environment configuration are not committed to the public repository. `visual-manifest.json` records the output dimensions, hash, crop range, and the original screenshot hash, and does not contain internal paths.

Generation method:

```bash
.venv/wechat/bin/python scripts/generate_large_scale_kubernetes_visuals.py \
  --grafana-screenshot /path/to/private/global-dashboard.png
```
