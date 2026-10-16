# Agent interruption and resumption schematic diagram

Both images are deterministic schematic diagrams at 1200×675, 16:9, not product screenshots or performance data.

| File | Purpose | Content source |
| --- | --- | --- |
| recovery-boundary.png | Explains committed steps, in-progress operations, and subsequent work | The one-hour task assumption in the main text; 32 and 37 minutes are only illustrative times |
| kubernetes-architecture.png | Explains the responsibilities of persistent execution components and replaceable Workers | The platform architecture recommendation in the main text; only shows partial dependencies |

Fonts, colors, and whitespace follow the repository's existing GLM / MiniMax M3 chart system, using Pillow and font boundary calculation.

Generation source: `scripts/generate_agent_durable_execution_assets.py`.

```bash
python scripts/generate_agent_durable_execution_assets.py
```

The diagrams do not contain company environment information, addresses, credentials, or measured performance values.
