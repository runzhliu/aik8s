---
name: cube-sandbox
description: "Execute requested Python code inside an isolated CubeSandbox MicroVM. Use when the user explicitly asks for CubeSandbox, MicroVM isolation, offline execution, or proof that code did not run on the OpenClaw host."
---

# CubeSandbox execution

Use the bundled `scripts/cube_agent_task.py` helper. It creates a short-lived,
offline CubeSandbox MicroVM, writes the requested Python program, executes it,
tests that public-network access is blocked, and destroys the sandbox in a
`finally` block.

## Required environment

The OpenClaw Gateway must provide:

- `CUBE_API_URL`
- `CUBE_PROXY_NODE_IP`
- `CUBE_PROXY_PORT_HTTP`
- `CUBE_PROXY_SCHEME`
- `CUBE_TEMPLATE_ID`
- `PYTHONUSERBASE` when the SDK is installed in a custom user base

Never print API keys or traffic-access tokens. Do not inspect unrelated
OpenClaw credentials.

## Run a task

```bash
python3 /home/node/.openclaw/workspace/skills/cube-sandbox/scripts/cube_agent_task.py \
  --python-code 'print(sum(i * i for i in range(1, 101)))'
```

For a live UI demonstration only, pass `--hold-seconds 30`. Never use the hold
option for normal tasks or values above 60 seconds.

Use a single-quoted Python expression without embedded single quotes. For more
complex programs, write the code to a file in the OpenClaw workspace and pass
`--python-file <path>`.

## Report

Return these facts to the user:

- `executor` is `cubesandbox-microvm`;
- program stdout and exit code;
- whether public network access was blocked;
- create latency for this one sample;
- cleanup result.

Do not claim success if cleanup is absent or the network test unexpectedly
succeeds.
