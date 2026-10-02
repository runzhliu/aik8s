"""CPU-only fault regressions. Synthetic results are never published as model data."""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from unattended import cases,should_stop_stage,run_child
from metrics import Metrics
from campaign import Campaign

HERE=Path(__file__).resolve().parent

class PolicyTests(unittest.TestCase):
    def test_failure_stops_only_its_stage(self):
        rows=[{'stage':'baseline','status':'FAILED'} for _ in range(3)]
        self.assertTrue(should_stop_stage(rows,'baseline'));self.assertFalse(should_stop_stage(rows,'decode'))
        rows.append({'stage':'baseline','status':'PASS'});self.assertFalse(should_stop_stage(rows,'baseline'))
    def test_context_scope(self):
        rows=cases(HERE/'cases.csv',['long'],32768)
        self.assertEqual(sum(r['status']=='NOT_EXECUTED' for r in rows),2)
        self.assertTrue(all(r['reason']=='context limit' for r in rows if r['input_tokens']>32768))
    def test_deadline_kills_process(self):
        with tempfile.TemporaryDirectory() as d:
            start=time.monotonic()
            self.assertEqual(run_child([sys.executable,'-c','import time;time.sleep(30)'],Path(d)/'log',.1),124)
            self.assertLess(time.monotonic()-start,3)
    def test_engine_exit_stops_child(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_child([sys.executable,'-c','import time;time.sleep(30)'],Path(d)/'log',10,health_check=lambda:False),125)
    def test_no_log_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'log';p.write_text('original failure')
            with self.assertRaises(FileExistsError):run_child(['true'],p,1)
            self.assertEqual(p.read_text(),'original failure')
    def test_failure_in_denominator_only_success_in_latency(self):
        m=Metrics()
        base={'engine':'sglang','case':'short','purpose':'measurement','finished_at':1,'usage':{'completion_tokens':128},'ttft_s':.1,'request_tpot_s':.02,'transport_e2e_s':3}
        m.add({**base,'success':True});m.add({**base,'success':False})
        text=m.render()
        self.assertIn('result="error"} 1',text);self.assertIn('purpose="measurement"} 128',text)
        self.assertIn('qwen38_client_ttft_seconds_count{engine="sglang",case="short",purpose="measurement"} 1',text)

class FakeAPI:
    def __init__(self):self.receipt={};self.deleted=[];self.objects={}
    def read_state(self,name):return self.receipt.get(name,{})
    def state(self,name,value):self.receipt[name]=copy.deepcopy(value)
    def get(self,kind,name):return self.objects.get(name)
    def delete_owned(self,name,run):self.deleted.append(name);self.objects.pop(name,None)

class CampaignTests(unittest.TestCase):
    def config(self,d):
        return {'run':'test','namespace':'test-namespace','output':d,'deadline_epoch':time.time()+2000,'bundle_sha256':'abc',
                'state_cm':'state','heartbeat_cm':'heartbeat','preflight_cm':'preflight','cleanup_cm':'cleanup',
                'engines':{e:{'pods':[{'metadata':{'name':e}}]} for e in ['sglang','vllm']}}
    def test_independent_engine_after_failure_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            api=FakeAPI();api.receipt['preflight']={'run':'test','status':'PASS','bundle_sha256':'abc'}
            c=Campaign(self.config(d),api);visited=[]
            def engine(e):
                visited.append(e);c.status['engines'][e]={'status':'BENCHMARK_FINISHED'}
                if e=='sglang':raise RuntimeError('synthetic NCCL failure')
            with patch.object(c,'engine',side_effect=engine),patch.object(c,'archive'),patch('campaign.subprocess.Popen'),patch('campaign.time.sleep'):
                c.run_campaign()
            self.assertEqual(visited,['sglang','vllm']);self.assertEqual(c.status['engines']['sglang']['status'],'FAILED')
            self.assertIn('sglang',api.deleted);self.assertIn('vllm',api.deleted)
            self.assertEqual(c.status['delivery']['articles'],'PENDING')
    def test_bad_preflight_never_starts_gpu(self):
        with tempfile.TemporaryDirectory() as d:
            c=Campaign(self.config(d),FakeAPI())
            with patch.object(c,'engine') as engine:
                with self.assertRaises(RuntimeError):c.run_campaign()
                engine.assert_not_called()
    def test_runtime_policy_skips_next_engine_without_interrupting_current(self):
        with tempfile.TemporaryDirectory() as d:
            api=FakeAPI();cfg=self.config(d);cfg['policy_cm']='policy';cfg['enabled_engines']=['sglang','vllm']
            api.receipt['preflight']={'run':'test','status':'PASS','bundle_sha256':'abc'}
            api.receipt['policy']={'run':'test','enabled_engines':['sglang','vllm'],'reason':'initial campaign scope'}
            c=Campaign(cfg,api);visited=[]
            def engine(e):
                visited.append(e);c.status['engines'][e]={'status':'BENCHMARK_FINISHED'}
                if e=='sglang':api.receipt['policy']={'run':'test','enabled_engines':['sglang'],'reason':'cost decision'}
            with patch.object(c,'engine',side_effect=engine),patch.object(c,'archive'),patch('campaign.subprocess.Popen'),patch('campaign.time.sleep'):
                c.run_campaign()
            self.assertEqual(visited,['sglang'])
            self.assertEqual(c.status['engines']['vllm']['status'],'NOT_EXECUTED')
            self.assertEqual(c.status['engines']['vllm']['reason'],'cost decision')
    def test_runtime_policy_cannot_expand_initial_scope(self):
        with tempfile.TemporaryDirectory() as d:
            api=FakeAPI();cfg=self.config(d);cfg['policy_cm']='policy';cfg['enabled_engines']=['sglang']
            api.receipt['policy']={'run':'test','enabled_engines':['sglang','vllm'],'reason':'late expansion'}
            c=Campaign(cfg,api)
            with self.assertRaisesRegex(RuntimeError,'invalid enabled_engines'):
                c.execution_policy()
    def test_failed_release_blocks_next_engine(self):
        with tempfile.TemporaryDirectory() as d:
            api=FakeAPI();api.receipt['preflight']={'run':'test','status':'PASS','bundle_sha256':'abc'}
            c=Campaign(self.config(d),api);seen=[]
            def engine(e):seen.append(e);c.status['engines'][e]={'status':'BENCHMARK_FINISHED'}
            with patch.object(c,'engine',side_effect=engine),patch.object(c,'archive'),patch.object(c,'release',side_effect=RuntimeError('unconfirmed')),patch('campaign.subprocess.Popen'),patch('campaign.time.sleep'):
                with self.assertRaises(RuntimeError):c.run_campaign()
            self.assertEqual(seen,['sglang']);self.assertTrue(c.status['cleanup_errors'])

class SmokeTests(unittest.TestCase):
    def test_optional_rejections_continue_all_independent_features(self):
        import smoke
        def chat(messages,**kwargs):
            if 'reasoning_effort' in kwargs:raise RuntimeError('HTTP400 optional effort unsupported')
            if kwargs.get('tools'):raise RuntimeError('unsupported tool')
            prompt=messages[-1]['content'];text='703' if '37' in prompt else 'amber-417'
            return {'choices':[{'message':{'role':'assistant','content':text}}]}
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'RESULT_FILE':d+'/result.json'}),patch.object(smoke,'request',return_value={'data':[{'id':smoke.MODEL}]}),patch.object(smoke,'chat',side_effect=chat),patch.object(smoke,'stream_chat',return_value=('703','')):
            self.assertEqual(smoke.main(),0)
            result=json.loads(Path(d+'/result.json').read_text());self.assertTrue(result['basic_gate_passed'])
            self.assertEqual(result['cases']['multi_turn']['status'],'PASS');self.assertEqual(result['cases']['tool_round_trip']['status'],'FAILED')
    def test_429_retries_bounded_and_records_attempts(self):
        import smoke,urllib.error
        from io import BytesIO
        def error(*a,**kw):raise urllib.error.HTTPError('url',429,'busy',{},BytesIO(b'busy'))
        with patch('smoke.urllib.request.urlopen',side_effect=error) as p,patch('smoke.time.sleep'),patch('smoke.trace') as trace:
            with self.assertRaises(RuntimeError):smoke.request('POST','/chat/completions',{'example':1})
            self.assertEqual(p.call_count,3);self.assertEqual(trace.call_count,3)

class StreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake=types.ModuleType('vllm.benchmarks.lib.endpoint_request_func')
        class Output:
            def __init__(self):self.itl=[];self.error='';self.ttft=0;self.success=False
        fake.RequestFuncOutput=Output;fake._update_payload_common=lambda p,r:None;fake._get_headers=lambda:{};fake._update_headers_common=lambda h,r:None
        mods={n:types.ModuleType(n) for n in ['vllm','vllm.benchmarks','vllm.benchmarks.lib']};mods['vllm.benchmarks.lib'].endpoint_request_func=fake
        cls.patch=patch.dict(sys.modules,mods);cls.patch.start()
        spec=importlib.util.spec_from_file_location('strict_test',HERE/'strict_bench.py');cls.strict=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.strict)
    @classmethod
    def tearDownClass(cls):cls.strict.POOL.shutdown(wait=True);cls.patch.stop()
    def test_split_utf8_crlf_sse(self):
        decoder=self.strict.SSEDecoder();data='data: {"choices":[{"text":"中文"}]}\r\n\r\ndata: [DONE]\n\n'.encode();events=[]
        for byte in data:events+=decoder.add_chunk(bytes([byte]))
        self.assertEqual(json.loads(events[0])['choices'][0]['text'],'中文');self.assertEqual(events[-1],'[DONE]')
    def test_invalid_streams_rejected_without_retry(self):
        strict=self.strict
        class Content:
            def __init__(self,rows):self.rows=rows
            async def iter_any(self):
                for row in self.rows:yield row
        class Response:
            status=200
            def __init__(self,rows):self.content=Content(rows)
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return False
        def event(obj):return ('data: '+(obj if isinstance(obj,str) else json.dumps(obj))+'\n\n').encode()
        async def run():
            base=[event({'choices':[{'text':'answer'}]}),event({'usage':{'prompt_tokens':4,'completion_tokens':8},'choices':[]}),event('[DONE]')]
            modes={'valid':base,'no_done':base[:-1],'no_usage':[base[0],base[-1]],'empty':[event({'choices':[{'text':''}]}),*base[1:]],'error':[base[0],event({'error':'failure'}),*base[1:]],'wrong_length':[base[0],event({'usage':{'prompt_tokens':4,'completion_tokens':7}}),base[-1]]}
            with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'QWEN_BENCH_RAW_DIR':d,'QWEN_BENCH_FIXTURE_ONLY':'1'}):
                for mode,rows in modes.items():
                    session=types.SimpleNamespace(post=lambda *a,rows=rows,**kw:Response(rows))
                    req=types.SimpleNamespace(model_name='test',model='test',prompt='p',output_len=8,logprobs=None,prompt_len=4,request_id=mode,ignore_eos=True,api_url='unused')
                    r=await strict.strict_request(req,session);self.assertEqual(r.success,mode=='valid',mode)
                for future in strict.WRITES:future.result()
                self.assertEqual(len(list(Path(d).glob('*.json'))),len(modes))
        asyncio.run(run())

if __name__=='__main__':unittest.main()
