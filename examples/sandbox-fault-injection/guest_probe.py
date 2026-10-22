"""Finite HTTP probes. Every request opens a fresh connection; no external destinations."""
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler, Request

allow, deny, case = sys.argv[1:]
opener = build_opener(ProxyHandler({}))
deadline = time.monotonic() + 240
with Path('/root/probe.jsonl').open('a', buffering=1) as log:
    seq = 0
    while time.monotonic() < deadline:
        for role, target in [('allow', allow), ('deny', deny)]:
            at = time.time()
            try:
                url = target + '/probe?' + urlencode({'case': case, 'seq': seq})
                with opener.open(Request(url, headers={'Connection': 'close'}), timeout=1) as response:
                    ok = response.status == 200 and json.load(response)['role'] == role
                result = {'ok': ok}
            except Exception as exc:
                result = {'ok': False, 'error': type(exc).__name__}
            log.write(json.dumps({'at': at, 'seq': seq, 'role': role, **result}) + '\n')
        seq += 1
        time.sleep(.5)
