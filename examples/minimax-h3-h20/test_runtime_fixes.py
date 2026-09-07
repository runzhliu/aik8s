#!/usr/bin/env python3
"""CPU regression checks against patched modules inside the pinned images."""
import argparse
import concurrent.futures
import json
import pickle
import threading
from types import SimpleNamespace
from unittest.mock import patch


def check_sglang():
    from sglang.multimodal_gen.runtime.managers.forward_context import (
        get_forward_context, set_forward_context,
    )
    from sglang.multimodal_gen.runtime.pipelines_core.stages.model_specific_stages.minimax_h3.stages.audio_encoding import MiniMaxH3AudioEncodingStage
    from sglang.multimodal_gen.runtime.pipelines_core.stages.model_specific_stages.minimax_h3 import material_io
    batch = SimpleNamespace(extra={})
    for fail in (False, True):
        def encode(actual_batch, server_args):
            context = get_forward_context()
            assert actual_batch is batch and context.forward_batch is batch
            assert context.current_timestep == 0 and context.attn_metadata is None
            if fail:
                raise ValueError('injected encoder failure')
            return batch
        stage = SimpleNamespace(_forward=encode)
        with set_forward_context(current_timestep=42, attn_metadata=None):
            outer = get_forward_context()
            with patch.object(material_io, 'minimax_h3_cleanup_temp_dirs') as cleanup:
                try:
                    assert MiniMaxH3AudioEncodingStage.forward(stage, batch, None) is batch
                    assert not fail
                except ValueError as exc:
                    assert fail and str(exc) == 'injected encoder failure'
                cleanup.assert_called_once_with(batch, owners=('material',))
            assert get_forward_context() is outer
    print(json.dumps({'test': 'audio context, exception propagation, cleanup and outer-context restoration', 'status': 'PASS'}))


def check_vllm():
    from vllm_omni.errors import OmniClientError, client_error_from_metadata
    from vllm_omni.diffusion.data import DiffusionOutput
    from vllm_omni.diffusion.executor.multiproc_executor import MultiprocDiffusionExecutor
    from vllm_omni.diffusion.worker.diffusion_worker import WorkerProc
    for original in (OmniClientError('bad duration'),
                     OmniClientError('too large', status_code=413, error_type='PayloadTooLarge'),
                     RuntimeError('injected CUDA failure')):
        received = []
        messages = iter([{'type': 'rpc', 'rpc_id': 'test', 'output_rank': 0}, {'type': 'shutdown'}])
        def execute(msg):
            raise original
        worker = SimpleNamespace(_running=True, mq=SimpleNamespace(dequeue=lambda **kw: next(messages)),
                                 gpu_id=0, result_mq=SimpleNamespace(enqueue=received.append),
                                 _execute_rpc=execute)
        WorkerProc._worker_busy_loop(worker)
        assert len(received) == 1
        envelope = pickle.loads(pickle.dumps(received[0]))
        stopped = threading.Event()
        def dequeue(**kw):
            stopped.set()
            return envelope
        future = concurrent.futures.Future()
        executor = SimpleNamespace(_pump_stop=stopped, _result_mq=SimpleNamespace(dequeue=dequeue),
            _futures_lock=threading.Lock(), _rpc_futures={'test': future})
        MultiprocDiffusionExecutor._result_pump(executor)
        exc = future.exception()
        assert type(exc) is type(original), (type(exc), type(original))
        assert str(exc) == str(original)
        output = DiffusionOutput.from_exception(exc)
        if isinstance(original, OmniClientError):
            assert output.error_status_code == original.status_code
            restored = client_error_from_metadata(output.error,
                status_code=output.error_status_code, error_type=output.error_type)
            assert restored.status_code == original.status_code
            assert restored.error_type == original.error_type
        else:
            assert output.error_status_code is None and output.error_type is None
    print(json.dumps({'test': 'worker RPC -> serialized envelope -> result pump -> diffusion output; 400/413 preserved, internal failure remains 500-class', 'status': 'PASS'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', choices=['sglang', 'vllm-omni'], required=True)
    a = p.parse_args()
    (check_sglang if a.engine == 'sglang' else check_vllm)()
