#!/usr/bin/env python3
"""Create a tiny synthetic SwanLab run without consuming a GPU."""

import math
import os
import time

import swanlab


api_key = os.environ["SWANLAB_API_KEY"]
api_host = os.environ["SWANLAB_API_HOST"]
project = os.getenv("SWANLAB_PROJECT", "training-infra-smoke")
experiment = os.getenv("SWANLAB_EXPERIMENT", "synthetic-loss")
steps = int(os.getenv("SWANLAB_SMOKE_STEPS", "6"))

swanlab.login(api_key=api_key, host=api_host, save=False)
swanlab.init(
    project=project,
    experiment_name=experiment,
    description="Synthetic metric-path smoke test; this is not model training.",
    tags=["smoke", "infrastructure"],
    config={"model": "synthetic", "steps": steps, "learning_rate": 2e-4},
)

for step in range(steps):
    swanlab.log(
        {
            "train/loss": 1.2 * math.exp(-0.42 * step) + 0.04,
            "train/learning_rate": 2e-4 * (1 - step / steps),
            "train/tokens_per_second": 920 + step * 17,
        }
    )
    time.sleep(0.4)

swanlab.finish()
print(f"SWANLAB_SMOKE_OK project={project} experiment={experiment} steps={steps}")
