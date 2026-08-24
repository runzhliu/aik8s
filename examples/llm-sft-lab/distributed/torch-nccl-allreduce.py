#!/usr/bin/env python3
"""Small torch.distributed collective benchmark for container/network smoke tests."""

import argparse
import json
import os
import socket
import time

import torch
import torch.distributed as dist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes-mb", default="1,16,64,256")
    parser.add_argument(
        "--collectives",
        default="all_reduce",
        help="Comma-separated collectives: all_reduce,all_to_all",
    )
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    local_rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(local_rank)
    dist.init_process_group("nccl")
    rank = dist.get_rank()
    world_size = dist.get_world_size()
    device = torch.device("cuda", local_rank)

    hosts: list[str | None] = [None] * world_size
    dist.all_gather_object(hosts, socket.gethostname())
    if rank == 0:
        print(
            "NCCL_ENV "
            + json.dumps(
                {
                    "world_size": world_size,
                    "hosts": hosts,
                    "nccl_version": torch.cuda.nccl.version(),
                    "nccl_ib_disable": os.getenv("NCCL_IB_DISABLE"),
                    "nccl_socket_ifname": os.getenv("NCCL_SOCKET_IFNAME"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    collectives = [item.strip() for item in args.collectives.split(",") if item.strip()]
    unknown = sorted(set(collectives) - {"all_reduce", "all_to_all"})
    if unknown:
        raise ValueError(f"Unsupported collectives: {', '.join(unknown)}")

    for collective in collectives:
        for size_mb in [int(item) for item in args.sizes_mb.split(",")]:
            size_bytes = size_mb * 1024 * 1024
            tensor = torch.ones(size_bytes // 4, dtype=torch.float32, device=device)
            output = torch.empty_like(tensor) if collective == "all_to_all" else None

            def run_collective() -> None:
                if collective == "all_reduce":
                    dist.all_reduce(tensor)
                else:
                    dist.all_to_all_single(output, tensor)

            dist.barrier()
            for _ in range(args.warmup):
                run_collective()
            torch.cuda.synchronize(device)

            dist.barrier()
            started = time.perf_counter()
            for _ in range(args.iterations):
                run_collective()
            torch.cuda.synchronize(device)
            elapsed = (time.perf_counter() - started) / args.iterations

            elapsed_tensor = torch.tensor(elapsed, dtype=torch.float64, device=device)
            dist.all_reduce(elapsed_tensor, op=dist.ReduceOp.MAX)
            critical_seconds = elapsed_tensor.item()
            alg_bw_gbytes_s = size_bytes / critical_seconds / 1e9
            if collective == "all_reduce":
                bus_bw_gbytes_s = alg_bw_gbytes_s * 2 * (world_size - 1) / world_size
            else:
                bus_bw_gbytes_s = alg_bw_gbytes_s * (world_size - 1) / world_size

            if rank == 0:
                print(
                    "NCCL_BENCH "
                    + json.dumps(
                        {
                            "collective": collective,
                            "size_mib_per_rank": size_mb,
                            "iterations": args.iterations,
                            "latency_ms": critical_seconds * 1000,
                            "algbw_GBps": alg_bw_gbytes_s,
                            "busbw_GBps": bus_bw_gbytes_s,
                        }
                    ),
                    flush=True,
                )

            del tensor, output
            torch.cuda.empty_cache()

    dist.destroy_process_group()


if __name__ == "__main__":
    main()
