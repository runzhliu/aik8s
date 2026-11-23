#!/usr/bin/env python3
"""Run one closed-loop streaming round and print its full request accounting as JSON.
Use only the model aliases allocated for your experiment.
"""

import concurrent.futures
import datetime
import argparse
import json
import random
import threading
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("url", help="OpenAI-compatible /v1/completions endpoint")
parser.add_argument("mode", choices=["A2", "B2", "A4", "AB", "probe"])
parser.add_argument("length", type=int, help="requested input tokens")
parser.add_argument("output", type=int, help="requested output tokens")
parser.add_argument("repeat", type=int, help="round number")
parser.add_argument("--per-lane", type=int, default=6)
parser.add_argument("--model-a", default="mc-qwen3")
parser.add_argument("--model-b", default="mc-qwen25")
parser.add_argument(
    "--salt", type=int, help="override the published per-mode seed offset"
)
args = parser.parse_args()
url, mode, length, output, repeat, per_lane = (
    args.url,
    args.mode,
    args.length,
    args.output,
    args.repeat,
    args.per_lane,
)
salt = (
    args.salt
    if args.salt is not None
    else (
        900000
        if mode == "probe"
        else 1000000 + 100000 * ["A2", "AB", "B2", "A4"].index(mode)
    )
)
if min(length, output, per_lane) <= 0 or repeat < 0:
    parser.error("lengths and lane count must be positive, round must be nonnegative")
A, B = args.model_a, args.model_b
configs = {
    "A2": [A] * 2,
    "B2": [B] * 2,
    "A4": [A] * 4,
    "AB": [A, A, B, B],
    "probe": [A, B],
}
models = configs[mode]
gate = threading.Barrier(len(models) + 1)


def lane(i):
    records = []
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    gate.wait()
    for j in range(per_lane):
        seed = salt + repeat * 10000 + length * 100 + i * per_lane + j
        rng = random.Random(seed)
        prompt = "".join(
            " " + rng.choice("abcdefghijklmnpqrstuvwxyz") for _ in range(length)
        )
        payload = {
            "model": models[i],
            "prompt": prompt,
            "max_tokens": output,
            "temperature": 0,
            "ignore_eos": True,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        row = {
            "model": models[i],
            "lane": i,
            "seq": j,
            "seed": seed,
            "http": 0,
            "done": False,
            "text": False,
        }
        chunks = []
        first = None
        last = None
        usage = {}
        finish = None
        returned = None
        start = time.monotonic()
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "routing-strategy": "random",
                },
            )
            with http.open(req, timeout=45) as response:
                row["http"] = response.status
                for line in response:
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        row["done"] = True
                        break
                    chunk = json.loads(data)
                    returned = chunk.get("model", returned)
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices", []):
                        t = choice.get("text", "")
                        if t:
                            now = time.monotonic()
                            if first is None:
                                first = now
                            last = now
                            chunks.append(t)
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
        except urllib.error.HTTPError as e:
            row.update(http=e.code, error=e.read(650).decode(errors="replace"))
        except Exception as e:
            row["error"] = str(e)[:400]
        text = "".join(chunks)
        end = time.monotonic()
        row.update(
            text=bool(text.strip()),
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            returned_model=returned,
            finish=finish,
            ttft_ms=round(1000 * (first - start), 3) if first is not None else None,
            tpot_ms=round(1000 * (last - first) / (usage["completion_tokens"] - 1), 3)
            if first is not None and usage.get("completion_tokens", 0) > 1
            else None,
            e2e_ms=round(1000 * (end - start), 3),
        )
        row["ok"] = (
            row["http"] == 200
            and row["text"]
            and row["done"]
            and returned == models[i]
            and finish == "length"
            and (row["prompt_tokens"], row["output_tokens"]) == (length, output)
        )
        records.append(row)
    return records


stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
with concurrent.futures.ThreadPoolExecutor(len(models)) as pool:
    futures = [pool.submit(lane, i) for i in range(len(models))]
    start = time.monotonic()
    gate.wait()
    rows = [r for future in futures for r in future.result()]
    elapsed = time.monotonic() - start
print(
    json.dumps(
        {
            "mode": mode,
            "input": length,
            "output": output,
            "round": repeat,
            "time": stamp,
            "wall_s": elapsed,
            "records": rows,
        }
    )
)
