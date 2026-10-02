#!/usr/bin/env python3
"""Validate collective results and pipeline-style send/receive on every GPU."""
import json
import os
from datetime import timedelta
from pathlib import Path
import time
import torch
import torch.distributed as dist

local=int(os.environ['LOCAL_RANK'])
torch.cuda.set_device(local)
dist.init_process_group('nccl',timeout=timedelta(seconds=300))
rank,world=dist.get_rank(),dist.get_world_size()
x=torch.empty(16*1024*1024,device='cuda',dtype=torch.float32)
for _ in range(3):
    x.fill_(rank+1)
    dist.all_reduce(x)
assert torch.all(x == world*(world+1)/2).item(), 'allreduce correctness'
torch.cuda.synchronize()
start=time.perf_counter()
for _ in range(10):
    x.fill_(1)
    dist.all_reduce(x)
torch.cuda.synchronize()
elapsed=time.perf_counter()-start
assert torch.all(x == world).item(), 'allreduce repeat correctness'
x.fill_(17 if rank==0 else 0)
dist.broadcast(x,src=0)
assert torch.all(x == 17).item(), 'broadcast correctness'
# Cross-node ring moves from local GPU i to GPU i on the next node.
stride=8 if world>8 else 1
src=(rank-stride)%world
dst=(rank+stride)%world
send=torch.full((1024*1024,),float(rank),device='cuda')
recv=torch.empty_like(send)
work=dist.batch_isend_irecv([dist.P2POp(dist.isend,send,dst),dist.P2POp(dist.irecv,recv,src)])
for w in work:w.wait()
assert torch.all(recv == src).item(), 'sendrecv correctness'
dist.barrier()
result={'status':'PASS','rank':rank,'world':world,'allreduce_GB_s':x.numel()*4*10/elapsed/1e9,
        'elapsed_s':elapsed,'collectives':['allreduce','broadcast','sendrecv'],'gpu':torch.cuda.get_device_name(local)}
folder=Path(os.environ['CHECK_OUTPUT']);folder.mkdir(parents=True,exist_ok=True)
(folder/('rank-'+str(rank)+'.json')).write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
dist.destroy_process_group()
