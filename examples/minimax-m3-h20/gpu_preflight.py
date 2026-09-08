import json, os, time
import torch
import torch.distributed as dist
rank=int(os.environ['LOCAL_RANK']);torch.cuda.set_device(rank)
dist.init_process_group('nccl');world=dist.get_world_size()
assert world==8,world
p=torch.cuda.get_device_properties(rank)
assert 'H20' in p.name and p.total_memory > 135*1024**3,(p.name,p.total_memory)
a=torch.randn((512,512),device='cuda',dtype=torch.bfloat16)
b=a @ a.T;assert torch.isfinite(b).all()
for size_mib in [1,16,128]:
 count=size_mib*1024*1024//4;x=torch.full((count,),rank+1.,device='cuda')
 dist.all_reduce(x);torch.cuda.synchronize();assert torch.all(x==world*(world+1)/2)
 x.zero_()
 for _ in range(5):dist.all_reduce(x)
 torch.cuda.synchronize();dist.barrier();start=time.perf_counter()
 for _ in range(20):dist.all_reduce(x)
 torch.cuda.synchronize();elapsed=(time.perf_counter()-start)/20
 times=torch.tensor(elapsed,device='cuda');dist.all_reduce(times,op=dist.ReduceOp.MAX)
 if rank==0:print(json.dumps({'check':'all_reduce','size_mib':size_mib,'ranks':world,'max_rank_latency_ms':times.item()*1000,'algorithm_GBps':size_mib*1024*1024/times.item()/1e9,'correctness':'PASS'}),flush=True)
if rank==0:print(json.dumps({'status':'GPU_PREFLIGHT_PASS','torch':torch.__version__,'cuda':torch.version.cuda,'gpus':world,'model_validation':'not_run'}),flush=True)
dist.destroy_process_group()
