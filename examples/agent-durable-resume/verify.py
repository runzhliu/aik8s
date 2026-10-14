"""Check real process termination and replay boundaries, in temporary directories."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DEMO = Path(__file__).with_name('demo.py')


def invoke(directory, command, crash_at=None):
    argv = [sys.executable, str(DEMO), command, '--data-dir', str(directory)]
    if crash_at:
        argv += ['--crash-at', crash_at]
    result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
    if result.returncode not in (0, 86):
        raise RuntimeError(result.stderr)
    lines = result.stdout.strip().splitlines()
    return result, json.loads(lines[-1]) if result.returncode == 0 else None


results = []
for failpoint in ('before-effect', 'after-effect'):
    with tempfile.TemporaryDirectory(prefix='agent-resume-') as directory:
        crashed, _ = invoke(directory, 'start', failpoint)
        assert crashed.returncode == 86
        _, interrupted = invoke(directory, 'inspect')
        resumed, completed = invoke(directory, 'resume')
        assert completed['state']['finished'] is True
        assert completed['next'] == []
        assert completed['node_executions'] == {'plan': 1, 'write_draft': 2, 'finish': 1}
        assert completed['tool_effects'] == 1
        _, no_op = invoke(directory, 'resume')
        assert no_op == completed, 'Completed run must not restart'
        results.append({'failpoint': failpoint, 'first_exit_code': crashed.returncode,
                        'interrupted': interrupted, 'completed': completed,
                        'crash_log': crashed.stdout.strip().splitlines(),
                        'resume_log': resumed.stdout.strip().splitlines()[:-1]})
print(json.dumps({'cases': results, 'verification': 'passed',
                  'scope': 'Local deterministic fixture, no LLM or remote API'},
                 indent=2, ensure_ascii=False))
