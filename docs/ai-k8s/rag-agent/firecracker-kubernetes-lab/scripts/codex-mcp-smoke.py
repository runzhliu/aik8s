#!/usr/bin/env python3
"""Validate the Codex stdio MCP facade and exercise its core tool path."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def result_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
    raise RuntimeError("MCP tool did not return an object")


async def run() -> None:
    environment = dict(os.environ)
    environment.pop("CUBE_ADAPTER_TOKEN", None)
    environment.update(
        {
            "CUBE_ADAPTER_URL": "http://127.0.0.1:18080",
            "CUBE_ADAPTER_TOKEN_FILE": "/root/.codex/cube-adapter-token",
            "CUBE_ADAPTER_PROFILE": "offline-code",
        }
    )
    parameters = StdioServerParameters(
        command="python3",
        args=["/workspace/cubesandbox-agent-adapter/cube_mcp_server.py"],
        env=environment,
    )

    lease_ref: str | None = None
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            required = {"cube_acquire", "cube_exec", "cube_status", "cube_release"}
            print("codex_mcp_core_tools=" + str(required <= names).lower())
            print("codex_mcp_tool_count=" + str(len(names)))

            try:
                acquired = result_payload(
                    await session.call_tool(
                        "cube_acquire",
                        {
                            "runtime": "mcp",
                            "session_key": "codex-firecracker-mcp",
                        },
                    )
                )
                lease_ref = str(acquired["lease_ref"])
                executed = result_payload(
                    await session.call_tool(
                        "cube_exec",
                        {
                            "lease_ref": lease_ref,
                            "command": "printf CODEX_MCP_FIRECRACKER_OK",
                        },
                    )
                )
                status = result_payload(
                    await session.call_tool("cube_status", {"lease_ref": lease_ref})
                )
                released = result_payload(
                    await session.call_tool(
                        "cube_release", {"lease_ref": lease_ref, "action": "kill"}
                    )
                )
                lease_ref = None
                print(
                    "codex_mcp_marker="
                    + str("CODEX_MCP_FIRECRACKER_OK" in str(executed)).lower()
                )
                print("codex_mcp_status_ok=" + str(bool(status)).lower())
                print("codex_mcp_release_ok=" + str(bool(released)).lower())
            finally:
                if lease_ref:
                    try:
                        await session.call_tool(
                            "cube_release",
                            {"lease_ref": lease_ref, "action": "kill"},
                        )
                    except Exception:
                        pass


if __name__ == "__main__":
    asyncio.run(run())
