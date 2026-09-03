#!/usr/bin/env python3
"""Exercise the Adapter path used by Codex without exposing lease identifiers."""

from __future__ import annotations

from cube_mcp_server import AdapterHttpClient


def main() -> None:
    client = AdapterHttpClient.from_env()
    lease_ref: str | None = None
    try:
        lease = client.post(
            "/v1/leases/acquire",
            {
                "runtime": "mcp",
                "session_key": "codex-firecracker",
                "profile": "offline-code",
            },
        )
        lease_ref = str(lease["lease_ref"])
        segment = client.segment(lease_ref)
        result = client.post(
            f"/v1/leases/{segment}/exec",
            {
                "command": "printf CODEX_FIRECRACKER_CUBESANDBOX_OK",
                "cwd": "/workspace",
                "timeout_ms": 120_000,
            },
        )
        status = client.post(f"/v1/leases/{segment}/status", {})
        released = client.post(
            f"/v1/leases/{segment}/release", {"action": "kill"}
        )
        lease_ref = None

        print(
            "codex_marker="
            + str("CODEX_FIRECRACKER_CUBESANDBOX_OK" in str(result)).lower()
        )
        print("codex_status_ok=" + str(bool(status)).lower())
        print("codex_release_ok=" + str(bool(released)).lower())
    finally:
        if lease_ref:
            try:
                client.post(
                    f"/v1/leases/{client.segment(lease_ref)}/release",
                    {"action": "kill"},
                )
            except Exception:
                pass


if __name__ == "__main__":
    main()
