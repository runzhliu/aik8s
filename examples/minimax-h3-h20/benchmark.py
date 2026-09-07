#!/usr/bin/env python3
"""T2VA driver. Dry-run by default; no model or evaluator downloads."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import math
import mimetypes
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid


def request(url, payload=None, timeout=7200, content_type="application/json"):
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": content_type})
    return urllib.request.urlopen(req, timeout=timeout)


def materialize_conditions(case):
    conditions = []
    for raw in case.get('conditions', []):
        condition = dict(raw)
        uri = condition['uri']
        if uri.startswith('file://'):
            path = Path(urllib.parse.unquote(urllib.parse.urlparse(uri).path))
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            condition['uri'] = 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode()
        conditions.append(condition)
    return conditions


def sglang_payload(case):
    return dict(model="MiniMaxAI/MiniMax-H3", prompt=case["prompt"], seconds=case["seconds"],
                task=case["task"], conditions=materialize_conditions(case), target=dict(short_edge=min(case["width"], case["height"]),
                aspect_ratio=case.get("aspect_ratio", "16:9"), duration_seconds=case["seconds"]),
                num_outputs_per_prompt=1, num_inference_steps=case["steps"],
                flow_shift=12.0, audio_flow_shift=3.0, seed=case["seed"])


def vllm_fields(case):
    extra = dict(task=case['task'], duration=case['seconds'], audio_flow_shift=3.0)
    fields = dict(prompt=case["prompt"], width=case["width"], height=case["height"],
                aspect_ratio=case.get("aspect_ratio", "16:9"), fps=24, num_inference_steps=case["steps"],
                flow_shift=12, seed=case["seed"])
    conditions = materialize_conditions(case)
    if case['task'] == 'fl2va':
        extra['frame_indices'] = [c['frame_index'] for c in conditions]
    for kind in ('image', 'video', 'audio'):
        values = [{kind + '_url': c['uri']} for c in conditions if c['type'] == kind]
        if values:
            fields[kind + '_reference'] = json.dumps(values)
    if any(c['type'] not in {'image', 'video', 'audio'} for c in conditions):
        raise ValueError('condition type has no vLLM adapter')
    fields['extra_params'] = json.dumps(extra)
    return fields


def multipart(fields):
    boundary = "h3-" + uuid.uuid4().hex
    data = bytearray()
    for name, value in fields.items():
        data.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                     f'\r\n\r\n{value}\r\n').encode())
    data.extend(f"--{boundary}--\r\n".encode())
    return bytes(data), "multipart/form-data; boundary=" + boundary


def run_one(args, case, output):
    start = time.monotonic()
    result = dict(engine=args.engine, case=case, output=str(output), status="FAIL",
                  polling_interval_s=args.poll_interval,
                  started_at=datetime.now(timezone.utc).isoformat())
    try:
        if args.engine == "sglang":
            payload = sglang_payload(case)
            output.with_suffix('.request.json').write_text(json.dumps(payload, ensure_ascii=False) + '\n')
            with request(args.base_url + "/v1/videos", payload, args.timeout) as r:
                job = json.load(r)
            result['submission'] = job
            job_id = str(job["id"])
            result["job_id"] = job_id
            job_url = args.base_url + "/v1/videos/" + urllib.parse.quote(job_id, safe="")
            while True:
                remaining = args.timeout - (time.monotonic() - start)
                if remaining <= 0:
                    raise TimeoutError("job deadline exceeded; inspect server before more requests")
                with request(job_url, timeout=min(30, remaining)) as r:
                    status = json.load(r)
                result['last_job_status'] = status
                if status.get("status") == "completed":
                    break
                if status.get("status") in {"failed", "cancelled", "canceled", "expired"}:
                    raise RuntimeError("server job failed: " + str(status.get("error", status["status"])))
                time.sleep(min(args.poll_interval, remaining))
            with request(job_url + "/content", timeout=args.timeout) as r, output.open("xb") as f:
                shutil.copyfileobj(r, f)
        else:
            fields = vllm_fields(case)
            output.with_suffix('.request.json').write_text(json.dumps(fields, ensure_ascii=False) + '\n')
            data, content_type = multipart(fields)
            with request(args.base_url + "/v1/videos/sync", data, args.timeout, content_type) as r:
                result['response_headers'] = {k:v for k,v in r.headers.items() if k.lower().startswith('x-')}
                with output.open("xb") as f:
                    shutil.copyfileobj(r, f)
        result["e2e_s"] = time.monotonic() - start
        result['download_completed_at'] = datetime.now(timezone.utc).isoformat()
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
                                "-of", "json", str(output)], check=True, text=True,
                               capture_output=True, timeout=120)
        media = json.loads(probe.stdout)
        result["media"] = media
        video = next(s for s in media["streams"] if s["codec_type"] == "video")
        audio = next(s for s in media["streams"] if s["codec_type"] == "audio")
        numerator, denominator = map(float, video["r_frame_rate"].split("/"))
        duration = float(media["format"]["duration"])
        if video["codec_name"] != "h264" or abs(numerator / denominator - 24) > .01:
            raise ValueError("unexpected video codec or FPS")
        if audio["codec_name"] != "aac" or audio["channels"] != 2 or int(audio["sample_rate"]) != 32000:
            raise ValueError("unexpected audio contract")
        if video["width"] != case["width"] or video["height"] != case["height"]:
            raise ValueError("actual dimensions differ; reconcile engine geometry before A/B")
        if not math.isfinite(duration) or abs(duration - case["seconds"]) > .3:
            raise ValueError("unexpected media duration")
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(output),
                        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                       check=True, capture_output=True, timeout=300)
        frames = int(video["nb_read_frames"])
        expected_frames = math.ceil((case['seconds'] * 24 - 5) / 17) * 17 + 5
        if frames != expected_frames:
            raise ValueError(f"decoded {frames} frames, expected H3 alignment {expected_frames}")
        result.update(status="PASS", frames=frames, duration_s=duration,
                      rtf=result["e2e_s"] / duration,
                      rtf_scope='legacy container duration; use rtf_video for comparisons',
                      video_duration_s=frames / 24,
                      rtf_video=result['e2e_s'] / (frames / 24))
    except urllib.error.HTTPError as exc:
        result.update(error=str(exc), http_status=exc.code,
                      response_body=exc.read(65536).decode('utf-8', errors='replace'),
                      elapsed_s=time.monotonic() - start)
    except Exception as exc:
        result.update(error=str(exc), elapsed_s=time.monotonic() - start)
    if output.exists():
        result['file_bytes'] = output.stat().st_size
        result['file_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", choices=["sglang", "vllm-omni"], required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    p.add_argument("--case", default="t2va-5s")
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--timeout", type=float, default=7200)
    p.add_argument("--poll-interval", type=float, default=1)
    p.add_argument("--output", type=Path, default=Path("results"))
    p.add_argument("--execute", action="store_true")
    p.add_argument("--skip-warmup", action="store_true", help="only after a separately recorded warmup")
    args = p.parse_args()
    args.base_url = args.base_url.rstrip("/")
    if min(args.concurrency, args.repeats, args.timeout, args.poll_interval) <= 0:
        p.error("concurrency, repeats, timeout and poll interval must be positive")
    cases = [c for c in json.loads(args.cases.read_text()) if c["id"] == args.case]
    if len(cases) != 1 or cases[0]["task"] not in {'t2va', 'fl2va', 'ref2va'}:
        p.error("select exactly one supported H3 case")
    case = cases[0]
    if not args.execute:
        payload = sglang_payload(case) if args.engine == "sglang" else vllm_fields(case)
        print(json.dumps(dict(mode="dry-run", engine=args.engine, payload=payload,
                              concurrency=args.concurrency, repeats=args.repeats), indent=2))
        return 0
    if not all(shutil.which(x) for x in ("ffmpeg", "ffprobe")):
        p.error("ffmpeg and ffprobe are required")
    run_dir = args.output / (args.engine + "-" + uuid.uuid4().hex[:12])
    run_dir.mkdir(parents=True, exist_ok=False)
    if not args.skip_warmup:
        warmup = run_one(args, case, run_dir / "warmup.mp4")
        if warmup["status"] != "PASS":
            (run_dir / 'summary.json').write_text(json.dumps(dict(
                engine=args.engine, case=case['id'], stage='warmup', status='FAIL',
                warmup=warmup), indent=2) + '\n')
            print(json.dumps(warmup)); return 1
    results = []
    batch_times = []
    for repeat in range(args.repeats):
        batch_start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(run_one, args, case, run_dir / f"r{repeat}-c{i}.mp4")
                       for i in range(args.concurrency)]
            batch = [f.result() for f in futures]
        results.extend(batch)
        batch_times.append(time.monotonic() - batch_start)
        if any(r["status"] != "PASS" for r in batch):
            break
    successes = [r for r in results if r["status"] == "PASS"]
    summary = dict(engine=args.engine, case=case["id"], samples=len(results),
                   concurrency=args.concurrency, requested_repeats=args.repeats,
                   success=len(successes), failed=len(results) - len(successes),
                   result_dir=str(run_dir), quality_review="pending-human-review",
                   warmup_skipped=args.skip_warmup,
                   batch_wall_s=batch_times,
                   throughput_scope="batch wall time including client media validation")
    if successes:
        times = [r["e2e_s"] for r in successes]
        summary.update(e2e_median_s=statistics.median(times), e2e_min_s=min(times), e2e_max_s=max(times))
        wall = sum(batch_times)
        summary.update(validated_videos_per_hour=len(successes) * 3600 / wall,
                       generated_video_seconds_per_wall_second=sum(r["duration_s"] for r in successes) / wall,
                       decoded_video_seconds_per_wall_second=sum(r['frames'] / 24 for r in successes) / wall,
                       actual_frame_counts=sorted({r["frames"] for r in successes}))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return int(summary["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
