"""Reproduce the CSV task against an already deployed OpenSandbox 1.1.1 server."""
import asyncio
from datetime import timedelta
import hashlib
import json
import os

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import WriteEntry


async def main():
    connection = ConnectionConfig(
        domain=os.getenv('OPENSANDBOX_DOMAIN', '127.0.0.1:38080'),
        api_key=os.environ['OPENSANDBOX_API_KEY'],
        protocol='http', use_server_proxy=True,
        request_timeout=timedelta(seconds=90),
    )
    sandbox = await Sandbox.create(
        os.getenv('OPENSANDBOX_IMAGE', 'python:3.12-slim'),
        connection_config=connection,
        timeout=timedelta(minutes=10), ready_timeout=timedelta(seconds=90),
        resource={'cpu': '500m', 'memory': '512Mi'},
        resource_requests={'cpu': '100m', 'memory': '128Mi'},
        secure_access=True,
    )
    try:
        data = 'region,amount\nEast,120\nWest,80\nEast,30\nNorth,70\nWest,20\nNorth,80\n'
        code = '''import csv, json
rows = list(csv.DictReader(open('/tmp/sales.csv')))
totals = {}
for row in rows:
    totals[row['region']] = totals.get(row['region'], 0) + int(row['amount'])
result = {'rows': len(rows), 'total': sum(totals.values()), 'by_region': totals}
open('/tmp/result.json', 'w').write(json.dumps(result, sort_keys=True))
print(json.dumps(result, sort_keys=True))
'''
        await sandbox.files.write_files([
            WriteEntry(path='/tmp/sales.csv', data=data),
            WriteEntry(path='/tmp/analyze.py', data=code),
        ])
        execution = await sandbox.commands.run('python /tmp/analyze.py')
        assert execution.exit_code == 0 and execution.error is None
        downloaded = await sandbox.files.read_file('/tmp/result.json')
        assert json.loads(downloaded) == {
            'rows': 6, 'total': 400,
            'by_region': {'East': 150, 'West': 100, 'North': 150},
        }
        original = await sandbox.files.read_file('/tmp/sales.csv')
        assert original == data
        print(json.dumps({'result': json.loads(downloaded),
                          'input_sha256': hashlib.sha256(original.encode()).hexdigest()}))
    finally:
        await sandbox.kill()
        await sandbox.close()


if __name__ == '__main__':
    asyncio.run(main())
