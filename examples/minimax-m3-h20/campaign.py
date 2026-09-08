#!/usr/bin/env python3
"""Bounded CPU-side acceptance and baseline runner, with durable progress.

Never allocates GPUs or changes deployments. The operator controls engine lifecycle.
The output directory must be a persistent mount. A PAUSE file stops child work.
"""
import csv
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

from validate_result import validate


def atomic(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def run():
    # Kubernetes ConfigMap projects files through versioned symlinks. Resolving
    # __file__ pins a revision directory that disappears after ConfigMap updates.
    scripts = Path(__file__).absolute().parent
    root = Path(os.environ['CAMPAIGN_DIR'])
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    engine = env['ENGINE']
    base = env['BASE_URL'].rstrip('/')
    lock = (root / '.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        lock.close()
        raise
    state = {'engine': engine, 'started_at': time.time(), 'completed_rounds': 0}

    def pulse(stage, **kwargs):
        state.update(stage=stage, heartbeat_at=time.time(), **kwargs)
        atomic(root / 'progress.json', state)
        print(json.dumps(state), flush=True)

    def paused():
        if (root / 'PAUSE').exists() or (root.parent / 'PAUSE').exists():
            raise RuntimeError('PAUSED: persistent pause marker exists')

    def child(command, target_env, log, budget):
        paused()
        with log.open('a') as output:
            p = subprocess.Popen(command, env=target_env, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + budget
            try:
                while p.poll() is None:
                    paused()
                    if time.monotonic() > deadline:
                        raise TimeoutError(f'Child exceeded {budget}s')
                    pulse(state['stage'], child_pid=p.pid, log_bytes=log.stat().st_size)
                    time.sleep(10)
                if p.returncode:
                    raise RuntimeError(f'Child exited {p.returncode}; see {log.name}')
            finally:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGTERM)
                    try:
                        p.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(p.pid, signal.SIGKILL)
                        p.wait()

    try:
        pulse('waiting_for_api')
        deadline = time.monotonic() + int(env.get('STARTUP_TIMEOUT', '3600'))
        while True:
            paused()
            try:
                with urllib.request.urlopen(base + '/v1/models', timeout=5) as response:
                    models = json.load(response)
                if any(m['id'] == env['MODEL'] for m in models['data']):
                    break
            except Exception as exc:
                pulse('waiting_for_api', last_api_error=str(exc))
            if time.monotonic() > deadline:
                raise TimeoutError('API readiness deadline reached')
            time.sleep(10)
        pulse('functional')
        functional = root / 'functional'
        report = functional / 'smoke-summary.json'
        if not report.exists():
            child(['python3', str(scripts / 'smoke.py')],
                  {**env, 'RESULTS_DIR': str(functional)}, root / 'functional.log', 2400)
        summary = json.loads(report.read_text())
        if summary.get('status') != 'PASS' or len(summary.get('cases', [])) != 12:
            raise RuntimeError('Functional acceptance failed; baseline not started')
        pulse('baseline')
        results = root / 'baseline'
        with (scripts / 'cases.csv').open() as source:
            cases = list(csv.DictReader(source))
        selected = [c for c in cases if c['stage'] == 'baseline']
        expected = sum(int(c['repeats']) for c in selected)
        # benchmark.sh runs each case's three rounds. Resume only whole validated cases;
        # preserve partial attempts, never overwrite previous results.
        for c in selected:
            paused()
            valid = True
            for repeat in range(1, int(c['repeats']) + 1):
                p = results / f"{engine}__{c['case_id']}__r{repeat}.json"
                if not p.exists():
                    valid = False
                    break
                validate(p, int(c['num_prompts']), int(c['output_tokens']))
            if not valid:
                existing = list(results.glob(f"{engine}__{c['case_id']}__r*.json"))
                if existing:
                    raise RuntimeError('Partial case retained; use a new campaign attempt')
                pulse('baseline', current_case=c['case_id'])
                child(['bash', str(scripts / 'benchmark.sh')],
                      {**env, 'EXECUTE': '1', 'STAGE': 'baseline',
                       'CASE_ID': c['case_id'], 'RESULTS_DIR': str(results)},
                      root / 'baseline.log', int(env.get('CASE_TIMEOUT', '5500')))
            for repeat in range(1, int(c['repeats']) + 1):
                validate(results / f"{engine}__{c['case_id']}__r{repeat}.json",
                         int(c['num_prompts']), int(c['output_tokens']))
            state['completed_rounds'] += int(c['repeats'])
            pulse('baseline', current_case=c['case_id'])
        assert state['completed_rounds'] == expected
        pulse('COMPLETE', expected_rounds=expected, finished_at=time.time())
        atomic(root / 'campaign-summary.json', state)
    except Exception as exc:
        pulse('STOPPED', error=str(exc), finished_at=time.time())
        atomic(root / 'campaign-summary.json', state)
        raise
    finally:
        lock.close()


if __name__ == '__main__':
    run()
