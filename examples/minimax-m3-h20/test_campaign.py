"""No-GPU regressions for the unattended controller and projected ConfigMaps."""
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

import campaign

REAL_SLEEP=time.sleep


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.scripts=self.root/'scripts';self.scripts.mkdir()
        self.output=self.root/'output'
        self.files={
            'campaign.py':'# projected controller entry',
            'cases.csv':'case_id,stage,input_tokens,output_tokens,concurrency,num_prompts,request_rate,repeats,description\ncase,baseline,1,2,1,1,inf,1,test\n',
            'smoke.py':'import json,os,pathlib\np=pathlib.Path(os.environ["RESULTS_DIR"]);p.mkdir(parents=True,exist_ok=True);(p/"smoke-summary.json").write_text(json.dumps({"status":"PASS","cases":[{}]*12}))\n',
            'benchmark.sh':'''python3 - <<'PY'
import json,os,pathlib
p=pathlib.Path(os.environ['RESULTS_DIR']);p.mkdir(parents=True,exist_ok=True)
(p/'vllm__case__r1.json').write_text(json.dumps({'completed':1,'total_output_tokens':2,'errors':[]}))
PY
'''}
        for name,body in self.files.items():(self.scripts/name).write_text(body)
        for p in [patch.dict(os.environ,{'CAMPAIGN_DIR':str(self.output),'ENGINE':'vllm',
                    'MODEL':'test','BASE_URL':'http://mock.invalid','STARTUP_TIMEOUT':'0'}),
                  patch.object(campaign,'__file__',str(self.scripts/'campaign.py')),
                  patch('campaign.time.sleep',side_effect=lambda _:REAL_SLEEP(.005)),
                  patch('campaign.urllib.request.urlopen',side_effect=lambda *a,**k:io.StringIO('{"data":[{"id":"test"}]}'))]:
            p.start();self.addCleanup(p.stop)

    def execute(self):
        with patch('sys.stdout',new=io.StringIO()):campaign.run()

    def state(self):return json.loads((self.output/'campaign-summary.json').read_text())

    def test_success(self):
        self.execute();self.assertEqual(self.state()['stage'],'COMPLETE')

    def test_not_ready_stops(self):
        with patch('campaign.urllib.request.urlopen',side_effect=urllib.error.URLError('not ready')):
            with self.assertRaises(TimeoutError):self.execute()
        self.assertEqual(self.state()['stage'],'STOPPED')

    def test_client_nonzero_stops(self):
        (self.scripts/'benchmark.sh').write_text('exit 7\n')
        with self.assertRaisesRegex(RuntimeError,'Child exited 7'):self.execute()
        self.assertEqual(self.state()['stage'],'STOPPED')

    def test_half_json_preserved(self):
        p=self.output/'baseline/vllm__case__r1.json';p.parent.mkdir(parents=True);p.write_text('{')
        with self.assertRaises(json.JSONDecodeError):self.execute()
        self.assertEqual(p.read_text(),'{')

    def test_validated_resume_skips_client(self):
        p=self.output/'baseline/vllm__case__r1.json';p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'completed':1,'total_output_tokens':2}))
        (self.scripts/'benchmark.sh').write_text('exit 7\n')
        self.execute();self.assertEqual(self.state()['stage'],'COMPLETE')

    def test_pause_before_work(self):
        self.output.mkdir();(self.output/'PAUSE').touch()
        with self.assertRaisesRegex(RuntimeError,'PAUSED'):self.execute()
        self.assertFalse((self.output/'functional').exists())

    def test_pause_terminates_child(self):
        (self.scripts/'smoke.py').write_text('import time;time.sleep(60)\n')
        def pause(_):
            (self.output/'PAUSE').touch();REAL_SLEEP(.005)
        with patch('campaign.time.sleep',side_effect=pause):
            with self.assertRaisesRegex(RuntimeError,'PAUSED'):self.execute()
        self.assertEqual(self.state()['stage'],'STOPPED')

    def test_configmap_rotation_during_readiness(self):
        old=self.scripts/'rev1';old.mkdir();new=self.scripts/'rev2';new.mkdir()
        for name,body in self.files.items():
            (self.scripts/name).unlink();(old/name).write_text(body);(new/name).write_text(body)
            (self.scripts/name).symlink_to('data/'+name)
        (self.scripts/'data').symlink_to('rev1')
        def rotate(*a,**k):
            (self.scripts/'data-new').symlink_to('rev2')
            os.replace(self.scripts/'data-new',self.scripts/'data');shutil.rmtree(old)
            return io.StringIO('{"data":[{"id":"test"}]}')
        with patch('campaign.urllib.request.urlopen',side_effect=rotate):self.execute()
        self.assertEqual(self.state()['stage'],'COMPLETE')


if __name__=='__main__':unittest.main()
