#!/usr/bin/env bash
set -euo pipefail
mkdir -p /outputs/runtime-preflight
findmnt -T "$MODEL_PATH" > /outputs/runtime-preflight/findmnt.txt
lsblk -o NAME,SIZE,TYPE,ROTA,MODEL > /outputs/runtime-preflight/lsblk.txt
nvidia-smi -q > /outputs/runtime-preflight/nvidia-smi.txt
nvidia-smi topo -m > /outputs/runtime-preflight/gpu-topology.txt
python3 - <<'PYNET' > /outputs/runtime-preflight/network.txt
import socket,fcntl,struct,json
from pathlib import Path
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
for _,name in socket.if_nameindex():
 try: ip=socket.inet_ntoa(fcntl.ioctl(s.fileno(),0x8915,struct.pack('256s',name.encode()[:15]))[20:24])
 except OSError: ip=None
 print(json.dumps({'interface':name,'ipv4':ip,'mtu':(Path('/sys/class/net')/name/'mtu').read_text().strip()}))
PYNET
ls -l /dev/infiniband > /outputs/runtime-preflight/ib-devices.txt
for i in {0..7}; do
  hca="/sys/class/infiniband/mlx5_bond_${i}"
  test -d "$hca"
  state="$(cat "$hca/ports/1/state")"
  [[ "$state" == *ACTIVE* ]]
  printf '%s %s gid3=%s type=%s\n' "mlx5_bond_${i}" "$state" "$(cat "$hca/ports/1/gids/3")" "$(cat "$hca/ports/1/gid_attrs/types/3")"
done > /outputs/runtime-preflight/rdma.txt
python3 - <<'PY'
import socket,os,json,torch
assert torch.cuda.device_count()==8
for port in (29588,30080,50080):
 s=socket.socket();s.bind(('0.0.0.0',port));s.close()
print(json.dumps({'gpus':torch.cuda.device_count(),'torch':torch.__version__,'cuda':torch.version.cuda,'node':os.environ['SGLANG_HOST_IP']}))
PY
python3 /scripts/preflight.py > /outputs/runtime-preflight/preflight.json
sglang serve --help > /outputs/runtime-preflight/sglang-help.txt
