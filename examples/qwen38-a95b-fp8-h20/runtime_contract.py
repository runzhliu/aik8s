#!/usr/bin/env python3
"""Zero GPU check against the exact installed API schema; no live model claims."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unattended import save

engine=os.environ['ENGINE'];here=Path(__file__).resolve().parent
modules=['sglang.srt.entrypoints.openai.protocol'] if engine=='sglang' else ['vllm.entrypoints.openai.protocol','vllm.entrypoints.openai.chat_completion.protocol']
cls=None
for module in modules:
    try:cls=getattr(importlib.import_module(module),'ChatCompletionRequest');break
    except (ImportError,AttributeError):continue
if cls is None:raise RuntimeError('cannot inspect installed chat API schema')
payload={'model':'qwen38-a95b-fp8','messages':[{'role':'user','content':'计算37×19，只回答数字。'}],
         'max_tokens':4096,'stream':True,'stream_options':{'include_usage':True},'temperature':0}
cls(**payload)
optional={}
for effort in ['low','medium','xhigh']:
    try:cls(**{**payload,'reasoning_effort':effort});optional[effort]='ACCEPTED_BY_SCHEMA'
    except Exception:optional[effort]='REJECTED_BY_SCHEMA'
if engine=='vllm':subprocess.run([sys.executable,str(here/'protocol_fixture.py')],check=True,timeout=180)
save('/outputs/runtime-contract.json',{'status':'PASS','engine':engine,'fixture_only':True,'reasoning_effort':optional})
