"""Disable the unstable NVLink throughput query before importing the exporter."""

from __future__ import annotations

import os


def _disabled_nvlink_throughput(self: object, interval: float | None = None) -> list[object]:
    del self, interval
    return []


if os.getenv("NVITOP_DISABLE_NVLINK_THROUGHPUT", "1").lower() not in {"0", "false", "no"}:
    from nvitop import Device

    Device.nvlink_throughput = _disabled_nvlink_throughput
