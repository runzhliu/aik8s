import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import prewarm


def shard(path, key, data=b'X'):
    header = json.dumps({key: {'dtype': 'U8', 'shape': [len(data)],
                                'data_offsets': [0, len(data)]}}).encode()
    path.write_bytes(struct.pack('<Q', len(header)) + header + data)


class PrewarmTest(unittest.TestCase):
    def test_incomplete_shard_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x'
            shard(p, 'weight')
            p.write_bytes(p.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                prewarm.inspect_shard(p, ['weight'])

    def test_wrong_index_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x'
            shard(p, 'weight')
            with self.assertRaises(ValueError):
                prewarm.inspect_shard(p, ['other'])

    def test_partial_to_complete_and_local_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / 'src', Path(d) / 'dst'
            src.mkdir()
            mapping = {'w{}'.format(i): 'model-{:05d}-of-00213.safetensors'.format(i)
                       for i in range(1, 214)}
            for key, name in mapping.items():
                shard(src / name, key)
            for name in prewarm.AUX:
                (src / name).write_text('{}' if name.endswith('.json') else 'test')
            (src / 'model.safetensors.index.json').write_text(json.dumps(
                {'metadata': {'total_size': 213}, 'weight_map': mapping}))
            name = mapping['w213']
            os.rename(str(src / name), str(src / (name + '.tmp')))
            args = argparse.Namespace(source=str(src), destination=str(dst), stable_seconds=0,
                                      scan_seconds=60, mib_per_second=10000, order_offset=0)
            control = Path(d) / 'control.json'
            control.write_text(json.dumps({'default_mib_s': 0}))
            args.control_file = str(control)
            obj = prewarm.Prewarm(args)
            state = obj.scan()
            self.assertEqual(state['source_complete_shards'], 212)
            self.assertEqual(state['source_pending_shards'], [name])
            self.assertFalse((dst / '.aik8s-complete').exists())
            # A source change between scan and copy must be skipped.
            changed = mapping['w1']
            os.utime(str(src / changed), None)
            obj.copy(changed, state['good'][changed])
            self.assertFalse((dst / changed).exists())
            os.rename(str(src / (name + '.tmp')), str(src / name))
            obj.scan_state = obj.scan()
            fake_disk = argparse.Namespace(free=10**13)
            with patch('prewarm.shutil.disk_usage', return_value=fake_disk), contextlib.redirect_stdout(io.StringIO()):
                obj.run()
            marker = json.loads((dst / '.aik8s-complete').read_text())
            self.assertEqual(marker['shards'], 213)
            self.assertEqual(marker['payload_bytes'], 213)
            self.assertEqual(obj.current_rate, 0)
            self.assertTrue(obj.local_matches(name, obj.scan()['good'][name]))
            (dst / name).write_bytes(b'broken')
            self.assertFalse(obj.local_matches(name, obj.scan()['good'][name]))


if __name__ == '__main__':
    unittest.main()
