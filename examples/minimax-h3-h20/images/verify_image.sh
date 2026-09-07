#!/usr/bin/env bash
# Run with a Docker account that may create CPU-only, network-isolated containers.
set -euo pipefail
engine="${1:?usage: bash verify_image.sh <sglang|vllm-omni> <image>}"
image="${2:?image required}"
case "$engine" in
  sglang)
    module=sglang.multimodal_gen.runtime.pipelines.minimax_h3_pipeline
    cli=sglang ;;
  vllm-omni)
    module=vllm_omni.diffusion.models.minimax_h3.pipeline_minimax_h3
    cli=vllm ;;
  *) echo 'unknown engine' >&2; exit 2 ;;
esac
docker image inspect "$image" --format '{{.Id}} {{.Architecture}} {{json .RepoDigests}}'
docker run --rm --network none --cpus 4 --memory 16g \
  -e NVIDIA_VISIBLE_DEVICES=void -e CUDA_VISIBLE_DEVICES='' \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e H3_IMPORT_MODULE="$module" -e H3_CLI="$cli" \
  --entrypoint bash "$image" -lc '
    set -euo pipefail
    python3 -m pip check
    python3 -c "import os, importlib, torch; print(torch.__version__, torch.version.cuda); importlib.import_module(os.environ[\"H3_IMPORT_MODULE\"])"
    if [[ "$H3_CLI" == vllm ]]; then
      # Probe the actual Omni entry point. Bare `vllm --help` also initializes
      # unrelated core-vLLM commands, whose DeviceConfig requires a GPU.
      "$H3_CLI" serve --omni --help
      ffmpeg -v error -f lavfi -i testsrc2=size=64x64:rate=24 -t 0.5 \
        -c:v libx264 -pix_fmt yuv420p /tmp/h3-ref-check.mp4
      python3 -c "from vllm_omni.diffusion.models.minimax_h3.reference_video import load_video_frames; frames=load_video_frames(\"/tmp/h3-ref-check.mp4\"); assert frames.shape == (12,64,64,3), frames.shape; print(\"H3_PYAV_REFERENCE_VIDEO_PASS\", frames.shape)"
    else
      "$H3_CLI" --help
    fi
    ffmpeg -version
    ffprobe -version
  '
echo 'CPU-only offline checks passed; GPU full generation is still required.'
