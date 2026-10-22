"""SDK worker inside a dedicated Pod. Never target host PIDs or a shared runtime home."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ENGINE, OP, CASE = sys.argv[1:]
ROOT = Path('/data/fault-evidence')
ROOT.mkdir(exist_ok=True)
META = ROOT / (ENGINE + '-' + CASE + '.json')
NAME = 'fault-' + CASE
runtime = None


async def open_box():
    global runtime
    if ENGINE == 'microsandbox':
        import microsandbox as m
        handle = await m.Sandbox.get(NAME)
        return await handle.connect()
    import boxlite as b
    regs = []
    if os.environ.get('REGISTRY_SKIP_VERIFY') == 'true':
        regs = [b.ImageRegistry(host=os.environ['GUEST_IMAGE'].split('/')[0], skip_verify=True)]
    runtime = b.Boxlite(b.Options(home_dir='/data/boxlite-fault-home', image_registries=regs))
    return await runtime.get(json.loads(META.read_text())['id'])


async def execute(box, command, args):
    if ENGINE == 'microsandbox':
        out = await box.exec(command, args, timeout=10)
        return out.exit_code, out.stdout_text, out.stderr_text
    out = await box.exec(command, args, timeout_secs=10)
    stdout, stderr = [], []
    async def drain(stream, target):
        async for chunk in stream:
            target.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    await asyncio.gather(drain(out.stdout(), stdout), drain(out.stderr(), stderr))
    result = await out.wait()
    return result.exit_code, ''.join(stdout), ''.join(stderr)


async def main():
    global runtime
    if OP == 'start':
        allow, deny = os.environ['ALLOW_URL'], os.environ['DENY_URL']
        if ENGINE == 'microsandbox':
            import microsandbox as m
            policy = m.NetworkPolicy(default_egress=m.Action.DENY, default_ingress=m.Action.DENY,
                rules=(m.Rule.allow(destination=m.Destination.ip(urlsplit(allow).hostname),
                                    protocol=m.Protocol.TCP, port=8080),))
            if os.environ.get('POLICY_MODE') == 'unrestricted':
                policy = m.NetworkPolicy.allow_all()
            box = await m.Sandbox.create(NAME, image='python-lab:local', cpus=1, memory=512,
                max_duration=300, detached=True, pull_policy=m.PullPolicy.NEVER,
                network=m.Network(policy=policy))
            await box.fs.write('/root/guest_probe.py', Path('/app/guest_probe.py').read_bytes())
            box_id = NAME
        else:
            import boxlite as b
            regs = []
            if os.environ.get('REGISTRY_SKIP_VERIFY') == 'true':
                regs = [b.ImageRegistry(host=os.environ['GUEST_IMAGE'].split('/')[0], skip_verify=True)]
            runtime = b.Boxlite(b.Options(home_dir='/data/boxlite-fault-home', image_registries=regs))
            box = await runtime.create(b.BoxOptions(image=os.environ['GUEST_IMAGE'], cpus=1,
                memory_mib=512, detach=True, auto_remove=False,
                network=b.NetworkSpec(mode='enabled', allow_net=[] if os.environ.get('POLICY_MODE') == 'unrestricted' else [urlsplit(allow).hostname])), name=NAME)
            await box.start()
            # A ConfigMap path is a symlink. Copy a regular file into the guest.
            plain = ROOT / 'probe-source.py'
            plain.write_bytes(Path('/app/guest_probe.py').read_bytes())
            await box.copy_in(str(plain), '/root/guest_probe.py')
            box_id = box.id
        code, stdout, stderr = await execute(box, 'sh', ['-c',
            'nohup python /root/guest_probe.py ' + allow + ' ' + deny + ' ' + CASE +
            ' >/tmp/probe-output.log 2>&1 </dev/null &'])
        assert code == 0, stderr
        meta = {'engine': ENGINE, 'case': CASE, 'id': box_id, 'sdk_pid': os.getpid(), 'at': time.time()}
        META.write_text(json.dumps(meta))
        print(json.dumps(meta), flush=True)
        deadline = time.monotonic() + 260
        while time.monotonic() < deadline:
            try:
                code, stdout, stderr = await execute(box, 'python', ['-c',
                    'import json;from pathlib import Path;print(json.dumps({"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"probes":[json.loads(x) for x in Path("/root/probe.jsonl").read_text().splitlines()]}))'])
                assert code == 0, stderr
                value = {'at': time.time(), 'available': True, **json.loads(stdout)}
            except Exception as exc:
                value = {'at': time.time(), 'available': False, 'error': repr(exc)}
            (ROOT / (ENGINE + '-' + CASE + '-guest.json')).write_text(json.dumps(value))
            await asyncio.sleep(2)
    elif OP == 'inspect':
        box = await open_box()
        code, stdout, stderr = await execute(box, 'python', ['-c',
            'import json;from pathlib import Path;print(json.dumps({"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"probes":[json.loads(x) for x in Path("/root/probe.jsonl").read_text().splitlines()]}))'])
        assert code == 0, stderr
        print(stdout, flush=True)
    elif OP == 'cleanup':
        if ENGINE == 'microsandbox':
            import microsandbox as m
            handle = await m.Sandbox.get(NAME)
            await handle.stop()
            await m.Sandbox.remove(NAME)
        else:
            box = await open_box()
            await box.stop()
            await runtime.remove(json.loads(META.read_text())['id'])
        print(json.dumps({'removed': NAME}))


asyncio.run(asyncio.wait_for(main(), 290))
