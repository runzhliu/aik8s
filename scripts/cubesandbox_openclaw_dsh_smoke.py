#!/usr/bin/env python3
"""Exercise the CubeSandbox capabilities needed by an Agent runtime adapter.

The script deliberately keeps the Agent control plane outside the sandbox. It
validates the remote execution plane that an OpenClaw tool/skill or a DSH
shell/filesystem provider would call.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

import requests
from cubesandbox import Sandbox


def elapsed_ms(started_at: float) -> int:
    return round((time.perf_counter() - started_at) * 1000)


def main() -> None:
    template = os.environ["CUBE_TEMPLATE_ID"]
    proxy_ip = os.environ.get("CUBE_PROXY_NODE_IP")
    proxy_port = int(os.environ.get("CUBE_PROXY_PORT_HTTP", "80"))
    sandbox_domain = os.environ.get("CUBE_SANDBOX_DOMAIN", "cube.app")

    sandbox = None
    result: Dict[str, Any] = {}

    try:
        started_at = time.perf_counter()
        sandbox = Sandbox.create(
            template=template,
            timeout=300,
            lifecycle={"on_timeout": "pause", "auto_resume": True},
            allow_internet_access=False,
            network={"allow_public_traffic": False},
            metadata={
                "runtime": "openclaw-or-dsh",
                "scope": "session",
                "purpose": "integration-smoke",
            },
        )
        result["create_ms"] = elapsed_ms(started_at)
        result["sandbox_ref"] = sandbox.sandbox_id[:8]

        sandbox.files.write(
            "/tmp/agent-session.json",
            json.dumps({"session": "demo", "turn": 1}),
        )
        shell_result = sandbox.commands.run(
            "printf 'shell=%s user=%s' ready \"$(id -u)\""
        )
        result["shell"] = shell_result.stdout
        result["workspace_before_pause"] = json.loads(
            sandbox.files.read("/tmp/agent-session.json")
        )

        code_result = sandbox.run_code("counter = 41\ncounter")
        result["code_before_pause"] = code_result.text

        network_result = sandbox.commands.run(
            "python3 -c \"import socket; "
            "s=socket.socket(); s.settimeout(1); "
            "s.connect(('1.1.1.1', 80))\"",
        )
        result["internet_blocked"] = network_result.exit_code != 0

        if proxy_ip:
            proxy_url = f"http://{proxy_ip}:{proxy_port}/health"
            proxy_host = f"49983-{sandbox.sandbox_id}.{sandbox_domain}"
            unauthenticated = requests.get(
                proxy_url,
                headers={"Host": proxy_host},
                timeout=3,
            )
            authenticated = requests.get(
                proxy_url,
                headers={
                    "Host": proxy_host,
                    "e2b-traffic-access-token": sandbox.traffic_access_token,
                },
                timeout=3,
            )
            result["public_without_token_status"] = unauthenticated.status_code
            result["public_with_token_status"] = authenticated.status_code

        started_at = time.perf_counter()
        sandbox.pause(wait=True)
        result["pause_ms"] = elapsed_ms(started_at)
        result["paused_state"] = sandbox.get_info().state

        started_at = time.perf_counter()
        # v0.7.0 returns the traffic-access token only from create(). Keeping
        # the original SDK object preserves that token across resume. A remote
        # adapter that reconnects in another process must persist the token
        # beside the sandbox ID and attach it to every data-plane request.
        sandbox.resume()
        result["resume_ms"] = elapsed_ms(started_at)
        result["resumed_state"] = sandbox.get_info().state
        result["workspace_after_resume"] = json.loads(
            sandbox.files.read("/tmp/agent-session.json")
        )
        result["code_after_resume"] = sandbox.run_code(
            "counter += 1\ncounter"
        ).text
    finally:
        if sandbox is not None:
            sandbox.kill()
            result["cleanup"] = "destroyed"

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
