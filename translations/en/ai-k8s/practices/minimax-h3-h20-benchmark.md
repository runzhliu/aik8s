---
title: "MiniMax H3 H20-3e Field Test: Full Audio-Video Generation, Dual Engine, and Persistence Acceptance"
description: "Using the same model snapshot on four H20-3e GPUs to validate SGLang Diffusion and vLLM-Omni, recording generation, concurrency, media checks, and raw artifact retention"
status: completed
---

# MiniMax H3 H20-3e Field Test: Full Audio-Video Generation, Dual Engine, and Persistence Acceptance

## Model Introduction: Positioning, Architecture, and Input/Output

MiniMax H3 is an audio-video generation system from MiniMax for multimodal content creation, supporting text, image, video, and audio conditions, and jointly generating visuals and native stereo sound. Its generation backbone, H3-Omni-Transformer, is a **33B-parameter dense, single-stream Transformer**, and the H3-Encoder uses **Qwen3-VL-32B** pretrained weights. The 33B figure refers to the generation backbone's parameter count; the condition encoder, Visual VAE, and Audio VAE are separate components, so this number cannot be used to directly estimate the GPU memory requirements of the entire system. [Official model architecture](https://huggingface.co/MiniMaxAI/MiniMax-H3#model-architecture)

### Why Test Both Visuals and Audio Simultaneously

H3-Base encodes each modality and organizes them into a unified sequence, with the same Omni Transformer jointly predicting the latent representations of video and audio, which are then decoded by their respective VAEs. Text and visual conditions pass through the H3-Encoder, visual content is also represented via the Visual VAE, and audio is encoded by the Audio VAE. This means the type and length of reference material can change the workload; validating only text generation does not cover the encoding paths for audio-bearing video or mixed references.

Approximately 13B parameters in the generation backbone reside in the AdaLN modulation branch. According to the official documentation, the relevant modulation results can be precomputed, so inference deployment does not need to keep this portion of weights resident. This is an optimization opportunity at the structural level, not an indication that the entire model only requires about 20B parameters to load; whether and how to adopt it depends on the runtime used. [Official backbone description](https://huggingface.co/MiniMaxAI/MiniMax-H3#h3-omni-transformer)

### What the Two Task Weight Sets Address

| Partition | Condition Input and Control Objective | Corresponding Experiments in This Article |
| --- | --- | --- |
| H3-Base-FL2VA | Zero, one, or two images as first frame or last frame; when no image, text-driven, generating the process between endpoints | Text, Chinese scenes, concurrency, first frame, last frame, first and last frame |
| H3-Base-Ref2VA | Combinations of images, videos, and audio, referencing conditions such as appearance, motion, and sound, allowing scene recombination | Single image, multiple images, silent/audio-bearing video, image plus audio, mixed references |

The two partitions use different task checkpoints, both containing the required encoding and decoding components. First-frame constraint and reference image are not the same type of control: the former specifies the opening frame, while the latter provides conditional cues, and cannot be used to promise pixel-perfect replication or arbitrary identity fidelity. [Official task specification](https://huggingface.co/MiniMaxAI/MiniMax-H3#model-variants-and-input-specifications)

The official output range is 4–15 seconds, 24 fps, 32 kHz stereo audio, supporting landscape, portrait, and other aspect ratios; Base generates at a short edge of 768 pixels by default. This article fixes 1344 × 768, covering 5/10/15 seconds, and does not present this as acceptance results for all aspect ratios, languages, and resolutions.

### Boundary Between Local Base and Full H3 System

The official full pipeline consists of **H3-Context-IR → H3-Base → H3-Regenerate-2K**. Context-IR is responsible for understanding and organizing multimodal input relationships, Base jointly generates 768p audio-video, and Regenerate-2K uses the existing results and original context to regenerate 2K output. The open-source local pipeline centers on Base; loading its weights does not automatically provide the hosted modules at either end. [Official system description](https://huggingface.co/MiniMaxAI/MiniMax-H3#system-overview)

The tests directly submit fixed prompts without invoking hosted context processing or 2K regeneration; what is measured below is the local Base's functionality, generation time, throughput, and media structure. Condition encoding, diffusion, and audio-video decoding each require actual requests; subject consistency, dialogue, and audio-visual synchronization are evaluated using separate quality criteria.

## Overview of This Round of Testing

**Both engines each completed 15 categories of configuration tests, all with passing records**: text duration, Chinese prompts, concurrency 1/2/4, first and last frames, and six types of reference material. Each engine's final summary selected 55 valid formal samples, totaling 110; warm-up, replaced samples, old-version repeated tests, and failure diagnostics are not counted in this number.

Here, "pass" means the request succeeded, media fully decoded, and the agreed dimensions, frame count, and audio track checks passed. No dedicated scoring was completed for real-person identity fidelity, dialogue accuracy, lip sync, or sound semantics.

The audio reference encoding issue in SGLang and the error status code issue in vLLM-Omni have been fixed and passed corresponding GPU re-tests; the original failure evidence is retained separately.

The supplementary tests for vLLM's five types of reference inputs included 15 formal generations and 5 warm-ups, all passing acceptance. The 20 MP4s and all 95 archive files from this continuation have been returned, with per-file size and SHA-256 matching; GPUs have been released, and remote originals are retained.

**These are engineering acceptance results with runtime condition notes, and cannot be used to rank the two engines for interference-free speed.** Early tests shared CPU, memory, and storage on the same machine; the vLLM later five reference task types also moved to another H20-3e node and switched to directly reading CFS. The runtime versions, storage methods, and per-sample records for each configuration are in the [final data CSV](../../assets/practices/minimax-h3-h20/final-results.csv) and [JSON](../../assets/practices/minimax-h3-h20/final-results.json).

## Experimental Scope

### Boundaries of This Round's Fixes

SGLang's audio encoding stage lacked the forward context required by the attention layer. Silent reference videos passed, but reference videos with an audio track triggered
`Forward context is not set`; [a similar upstream issue](https://github.com/sgl-project/sglang/issues/35447) records the same call chain.
This patch sets and restores context at that stage while preserving the original exception propagation and input cleanup.

vLLM-Omni's model validation already threw `OmniClientError` with a 400 status code, but the asynchronous RPC envelope only retained the error text,
and the result pump and executor downgraded it to a plain `RuntimeError`, ultimately causing overlong-duration requests to return 500.
This patch passes through and restores client error metadata; genuine internal errors remain server errors, and the acceptance criteria for invalid requests have not been relaxed.

Both fixes passed CPU regression tests within a fixed image. GPU re-tests cover SGLang's remaining audio reference configurations, as well as vLLM's
abnormal requests, normal generation recovery, 2/4 concurrency, first and last frames, and the full reference input matrix. The original failing runs and fixed runs are retained separately.
Model weights, seeds, and sampling parameters are unchanged, but the runtime has added local patches; corresponding results are marked as fixed versions and cannot be passed off as unmodified upstream results.
The complete patch identifiers, file SHA-256, patch content, and original files are archived with the startup records; the text uniformly refers to them as the audio context and error propagation fix versions.

After the fixes, SGLang completed 3 formal generations each for the three configurations of audio-bearing video, image plus audio, and mixed references; vLLM's four types of invalid requests all returned HTTP 400, and subsequent normal generation recovery passed.
vLLM also re-ran five configurations—concurrency 2/4, first frame, last frame, and first and last frames—with a total of 27 formal samples passing. The 5/10/15-second single-concurrency and Chinese baseline results retain the original version results and are not passed off as post-fix re-test values.

### Baseline and Resource Usage

Using the full MiniMax H3 weights, preserving the original BF16/FP32 mixed precision; not loading Turbo, FastH3, quantized weights, or cache acceleration.
Each runtime uses four H20-3e GPUs, first loading the FL2VA partition to complete text generation and first/last frame control, then validating Ref2VA.
SGLang's FL2VA matrix was completed independently first; samples overlapped by an early brief second-engine startup were excluded and re-tested.
Some configurations ran in parallel on the same eight-GPU node with four GPUs per engine. The two GPU sets were allocated independently, but CPU, memory, storage, and switch interconnect remained shared, so such data cannot be directly interpreted as interference-free engine comparisons with independent run windows.
Additionally, some vLLM measurement windows overlapped with independent video creation tasks on the same machine; the creation generation and post-dubbing are not included in formal statistics, but the same-machine load is a condition to retain when comparing.
The SGLang multi-image configuration interrupted by the creation task was fully re-run in a separate results directory; the unfinished old configuration is retained for diagnostics and not included in formal statistics.
Formal stress-test inputs include text, two images for first and last frames, three reference images, two 5-second reference videos, and one 5-second stereo WAV.
These stress-test reference materials are deterministically generated by repository scripts and contain no external people, accounts, or production information.

The evaluation target is the open-source **H3-Base 768p local generation pipeline**: the FL2VA partition serves text and first/last frame tasks,
and the Ref2VA partition is used for multimodal references. Prompts go directly into the local model. The official full system additionally includes hosted H3-Context-IR
preprocessing and H3-Regenerate-2K; the applicability of this round's results is limited to the above local configuration.
[Official model card](https://huggingface.co/MiniMaxAI/MiniMax-H3),
[SGLang H3 Cookbook](https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3),
[vLLM H3 Recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3) provide capability and interface references.

![Experiment flow and media acceptance objectives](../../assets/practices/minimax-h3-h20/workflow.png)

## Primer: From Text-to-Video to Making Real-Person Photos Move

"AI video" includes several different input modes. Determining what you want to preserve first, then choosing the task, makes it easier to locate problems than simply adding more prompt text.

| What you want to do | Input | Corresponding H3 task | Key checks |
| --- | --- | --- | --- |
| Create a character and scene from text | Text | T2VA, using FL2VA weight partition | Whether motion, scene, and sound match the description |
| Extend your own photo into a sequence of motion | Photo as first frame, plus motion description | FL2VA, first-frame condition | Opening composition, continuity of face and subsequent motion |
| Specify a start and an end | Two images for first and last frames, plus transition description | FL2VA, first and last frame condition | Whether motion between the two endpoints is reasonable |
| Have the person in a reference photo appear in a new scene | Person reference image, plus new scene description | Ref2VA | Whether the person's appearance is maintained and the scene is recombined as requested |

SGLang's H3 interface marks first and last images as `keyframe` and reference images as `reference`. The former constrains video endpoints,
while the latter provides appearance, style, or composition cues and may re-frame and crop. See the
[official H3 interface description](https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3) for the mapping.

**This round's stress-test materials are toys, geometric shapes, and natural scenes; the portrait workflow below is a usage example and has not undergone dedicated real-person identity fidelity or lip-sync testing.**
Photos serve as conditions for this inference; submitting a reference image once does not train a dedicated model that permanently remembers that person.

### How to Turn a Photo of Yourself into a 5-Second Video

The following are practical suggestions for step-by-step troubleshooting, not a promise of face fidelity rate. Use your own photo or one with explicit authorization; when publishing works, note AI generation,
and if using a person's voice, separately confirm the authorization scope of the voice material.

1. **Prepare the photo.** Start with a half-body photo of a single person with a clear face, even lighting, and minimal occlusion, retaining the full head and motion space.
   This example follows the landscape test configuration; first prepare a suitable landscape composition, and do not directly stretch a portrait face.
2. **Start with small motions.** Choose first-frame mode and generate a 5-second, single-shot video; first try natural blinking, a slight smile, or a small head turn, observing changes item by item.
3. **Clearly specify what to keep and what to change.** Keep the person, clothing, background, and camera, and write only one action for the change. Information already in the photo need not be re-specified with contradictory text.
4. **Check frame by frame before increasing difficulty.** Examine the face shape, eyes, teeth, hairline at the beginning, middle, and end, as well as changes during head turns and occlusion; watch the full video to confirm there is no sudden face change or jump.
5. **Keep reproducible records.** Retain the input photo, prompt, seed, parameters, and original video; when adjusting, change only one major condition at a time. A fixed seed facilitates comparison but does not guarantee that different engines generate the same face.

A prompt suitable for a first attempt is:

> The person in the photo keeps their original clothing and hairstyle, faces the camera, blinks naturally once, then smiles slightly. Fixed half-body shot, keeping background and lighting stable,
> continuous single shot, no cuts. The person does not speak; only slight indoor ambient sound, no background music.

You can break the prompt into four parts: "subject and scene → motion process → camera → sound". For complex shots, refer to the
[official basic task prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md)
to refine timelines, speakers, and sound layers; this example's short prompt does not invoke the hosted H3-Context-IR.

### How to Connect to This Repository's Test Client

In a separate portrait acceptance session, use the already-started **FL2VA service**. First place the photo into the material mount directory, confirm the container where the test client resides
can read `/fixtures/portrait.png`, then save the following content as `/outputs/portrait-cases.json`.
This is a request template for the user to provide an image, not an already-generated face case.

```json
[
  {
    "id": "portrait-first-frame",
    "task": "fl2va",
    "prompt": "照片中的人物保持原有服装和发型，面向镜头，自然眨眼一次，随后轻微微笑。固定半身镜头，保持背景和光照稳定，连续单镜头，无切换。人物不说话，仅有轻微室内环境声，无背景音乐。",
    "seconds": 5,
    "width": 1344,
    "height": 768,
    "seed": 4101,
    "steps": 50,
    "conditions": [
      {
        "type": "image",
        "uri": "file:///fixtures/portrait.png",
        "role": "keyframe",
        "frame_index": 0
      }
    ]
  }
]
```

Execute in a container with the repository test scripts and FFmpeg:

```bash
python3 /h3-launch/benchmark.py \
  --engine sglang --base-url http://127.0.0.1:8000 \
  --cases /outputs/portrait-cases.json --case portrait-first-frame \
  --concurrency 1 --repeats 1 --output /outputs/portrait-demo --execute
```

The client will encode the local photo and upload it, first generating a warm-up video, then a formal video, saving the MP4, request, and media check results separately.
`/outputs/portrait-demo` should continue to be mounted to a persistent directory. This portrait demonstration uses a separate directory and time slot and is not mixed into this article's original stress-test data.
`frame_index: 0` indicates the first frame, and `-1` indicates the last frame; only when first and last constraints are needed are both images passed simultaneously.

### What If You Want to Keep This Person but Change the Scene

You can try Ref2VA: the image serves as a person's appearance reference, and text describes the new scene and motion. You must use a service that has already loaded the **Ref2VA weight partition**,
and change the request `task` to `ref2va`, the image `role` to `reference`, and remove `frame_index`.
The prompt can be written as:

> Use the person in &lt;Picture 1&gt; as the appearance reference, keeping facial features, hairstyle, and clothing. The person stands in a bright study, looks at the camera, and nods gently.
> Half-body fixed shot, single continuous shot, soft natural light; the person does not speak, only quiet indoor ambient sound.

First establish a baseline with one clear photo, then try adding other angles of the same person, clarifying that each image corresponds to the same person; compare whether the added material improves results.
Multiple images do not automatically mean more accurate identity control and also increase computational workload. H3 officially allows Ref2VA to accept multiple images; see the
[official input specification](https://huggingface.co/MiniMaxAI/MiniMax-H3#model-variants-and-input-specifications) for the specific limit;
for expressing reference numbering and material relationships, refer to the
[official reference task prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md).

### Why "Looks Like," "Sounds Like," and "Lip Sync" Should Be Evaluated Separately

A face photo provides only visual information and cannot provide the person's real voice. Consistent appearance, accurately speaking lines, similar voice timbre, and lip-sync with sound
are different acceptance objectives. H3's reference partition can accept audio, but this cannot guarantee voice replication or word-for-word lip alignment for any person;
this round's checks that the audio track exists and is decodable do not mean these objectives have been passed.

When doing person voice-over, first validate a short clip without speech, then add one short line, checking text, pronunciation, lip movements, and audio-visual timing separately.
If the project requires a specific voice-over, evaluate "confirmed voice-over + separately accepted lip-sync step" as another workflow,
and do not attribute its effect to this round's H3 baseline. When output contains real faces, still review segment by segment before using in public works.

| Common phenomenon | Troubleshooting and adjustment direction |
| --- | --- |
| Looks like the person at the start, but changes noticeably after turning head | Check original image clarity and occlusion, first reduce the head-turn range, then compare reference images from other angles |
| Person is similar, but background is also retained | Check whether first-frame mode was selected; for new scene needs, test Ref2VA separately and clarify the reference sources for person and scene |
| Deformation when opening mouth, showing teeth, or hand covering face | Test expressions, hand movements, and occlusion separately, and check the entire process rather than only start and end screenshots |
| Video has sound, but content or lip sync is wrong | Separately check lines, speaker, sound, and lip movements; MP4 media validation cannot replace this check |

### How to Assemble Short Shots into an AI Short Drama

A long drama is usually composed of multiple short shots edited together. First break the script into six items: "character, location, action, dialogue, sound, duration," then keep each shot's
length within the range supported by the model interface used. A sample structure convenient for acceptance is: 6 dynamic shots of 8 seconds each, plus a 6-second opening and a 6-second ending, totaling 60 seconds.

1. **Unified character reference.** Determine reference images for each original or licensed character, recording hairstyle, costume, lighting, and framing; re-check appearance after scene changes.
2. **Arrange only a small amount of action per shot.** Dialogue can be split into single-person shots at fixed camera positions, two-person wide shots handle spatial context, and hand close-ups and environment shots handle transitions.
3. **Clarify the dubbing approach.** The H3 native audio track, post-production narration, and additional lip-sync should be recorded separately. For shots using inner voice or narration, the character may remain on screen without speaking.
4. **Accept once more after editing.** Unify aspect ratio, frame rate, subtitle safe area, and volume; check seams, subtitle timing, and full-file decoding; also keep the original MP4 and all post-production versions.

Total production time also includes reference image preparation, shot retries, dubbing, editing, and checking. When estimating, use actual per-shot time and available resources, and reserve rework time; character consistency across multiple shots still needs to be checked segment by segment. This is an independent creative workflow and does not replace the fixed-asset performance tests described earlier.

## Hardware, models, and versions

| Item | This round's configuration |
| --- | --- |
| GPU | Single node, 4 × NVIDIA H20-3e per engine; 8 cards shared when running in parallel, 143771 MiB per card |
| Driver | 580.126.20 |
| GPU interconnect | Allocated four cards show pairwise `NV18` |
| GPU power cap | `nvidia-smi` reports 500 W per card; not equal to actual operating power |
| Runtime clock snapshot | At sampling time, four cards at SM 1980 MHz, GPU memory 3201 MHz; observation valid only at that moment |
| SGLang source | `71de97b264b04dcd514cf904003028aefe9775c8` |
| vLLM-Omni source | `48298030d4b3c320b858dd98934c01babdd320ce`, core-vLLM 0.26.0 |
| SGLang actual runtime dependencies | Python 3.12.3, PyTorch 2.13.0+cu130, Diffusers 0.37.0, Transformers 5.12.1 |
| vLLM-Omni actual runtime dependencies | Python 3.12.13, PyTorch 2.11.0+cu130, Diffusers 0.38.0, Transformers 5.14.1 |
| SGLang topology | Ulysses 4, encoder-parallel auto, original precision resident |
| vLLM-Omni actual topology | USP 4 / Ring 1, text encoder TP 4, VAE tile parallel 4 |
| Compilation settings | SGLang speed mode disables torch.compile; vLLM-Omni enables deferred regional torch.compile (dynamic=True) on 52 DiT block modules by default |
| Model loading | Early shared source → NVMe; vLLM's latter five Ref2VA classes read read-only CFS directly |
| Output | Independent persistent hostPath; each batch returned locally and SHA-256 verified |

### What else was checked after model synchronization completed

The shared source has 296 files, totaling **498,573,081,306 bytes**. Copying to NVMe took **593.13 seconds**, approximately 840.6 MB/s. This is the wall-clock result of a dual-threaded copy in a single sequential task, including all directory files, and is not an independent storage bandwidth benchmark. The target directory was confirmed via device mapping to be backed by two NVMe drives.

Source and target directories match file-by-file in name and size; safetensors headers, tensor data ranges, and shard index reference checks passed. SHA-256 of small files and weight headers was also compared. As originally planned, no full-content hash was performed on the approximately 499 GB of weights.

CFS did not retain the original Git revision, indicating the files also differ from the current Hub main branch. Therefore, this round uses
`metadata-sha256:de4928038b821d696663188738950370313900904da5dd69cb03c62d385b36e0`
to identify the preserved source snapshot. `42ed227ee7df40d41602854ae760620d6eb651fe` is the upstream reference revision used to verify the component manifest, and **does not prove that CFS actually comes from that commit**. The two engines reused the verified NVMe files early on; vLLM's continued run verified the CFS source against the same snapshot identifier and loaded directly, without re-warming NVMe.

### CFS direct loading and startup-period resources

A single four-card Pod can load read-only CFS directly; no separate NVMe copy of the model directory is needed. The model snapshot, shard references, and file integrity must still be verified first, and output must go to a separate writable hostPath.
This round's vLLM continued run used the following environment and startup parameters:

```bash
MODEL_STORAGE=cfs
MODEL_PATH=/models-cfs/MiniMax-H3/v1
MODEL_IDENTITY_FILE=/outputs/model-identity.json
# launch.sh 对 CFS 模式默认补充：
# --init-timeout 3600 --stage-init-timeout 3600
```

`model-identity.json` is a report produced by source verification, not a hand-written PASS marker. The report's verification scope must be explicit: this round compared file sizes, weight headers, and small-file hashes, and did not hash all weight contents. The read-only PVC is mounted at `/models-cfs`, and test artifacts are written to a separate writable mount.

Three types of startup/resource issues were actually encountered:

| Symptom | Diagnosis and handling | Statistical treatment |
| --- | --- | --- |
| `OOMKilled` during Ref2VA loading | Host memory limit adjusted from 384 GiB to 768 GiB; retry observed load peak of approximately 470.91 GiB | Load failures not counted in generation time |
| First multi-image warm-up ran out of GPU memory after scheduling to a 96 GB H20 | Re-verified the actually allocated GPU model and GPU memory, switched back to H20-3e | All runs on wrong hardware excluded, diagnostics retained |
| CFS loading terminated after exceeding the default 600 seconds | Initialization and stage initialization timeouts both set to 3600 seconds; successful startup took approximately 16 minutes | Startup and steady-state requests recorded separately |

This successful CFS load does not constitute a storage comparison experiment proving CFS is faster or slower than NVMe. Avoid misjudging model failure due to monitoring connection timeouts: client monitoring and tests executed independently inside the Pod must record status separately, and final artifacts must be verified after reconnection.

### Local path auto-detection issue

The contingency plan initially named the container directory `/models-nvme/MiniMax-H3/v1`. During actual startup, the SGLang CLI first mis-selected the language model entry point; after explicitly setting diffusion, it still could not auto-resolve because the root directory lacked `model_index.json`.

The H3 native registration rules in the pinned source code recognize `MiniMaxAI/MiniMax-H3`, then enter the `FL2VA` or `Ref2VA`
partition to read the actual components. Therefore, the same hostPath was ultimately mounted as `/models-nvme/MiniMaxAI/MiniMax-H3`,
with `--model-type diffusion --backend sglang --model-id MiniMax-H3` explicitly specified.
This fix does not move, rewrite, or convert weights, nor does it use symlinks as a substitute for model format conversion.

## Request and timing methodology

All three primary requests use 768p short edge, 1344 × 768, 24 fps, 50 sampling points, with video/audio flow shift of 12/3 respectively.
Fixed prompts and seeds; the same seed does not mean both engines produce pixel-identical output.
The 5, 10, and 15 second cases use fixed prompts and seeds for the toy car, rainy pond, and paper sailboat respectively.
Cross-engine comparisons reuse exactly the same corresponding requests; the cross-duration table is an observation of different workloads, not an ablation experiment that only changes duration.

H3's temporal length is aligned per `17n+5`. The expected frame counts for the 5, 10, and 15 second requests are 124, 243, and 362 respectively.
The primary comparison uses the actual decoded frame count; the 50 sampling points and actual DiT execution count are recorded separately.

Each configuration is warmed up once first; the formal single-concurrency sample count is 3; concurrency 2 and 4 each run 3 batches of 2 or 4 requests per batch.
Any timeout, generation failure, OOM, or media acceptance failure stops further concurrency scaling and leaves a failure record.

Client end-to-end time starts at request construction and submission and ends when the complete MP4 download finishes; ffprobe/ffmpeg verification runs after timing ends.
SGLang uses asynchronous submission, 1-second polling, and download; vLLM-Omni uses synchronous video responses. Conditional assets use byte-identical
Data URIs on both sides, and upload cost is included in end-to-end time. Protocol differences are retained; client-side time is not directly called model kernel time.

Batch throughput includes client media acceptance time, and the metric name is explicitly written as "videos/hour including verification". Single-request RTF uses
`端到端秒数 / 实际视频秒数`, lower is better. Small samples report only raw values, median, and range, and no reliable P99 is reported from them.

## Which prompts were actually used in testing

The following four are the actual raw prompts submitted, verified against both engines' formal request records. They all request 5 seconds, 1344 × 768, 50 sampling points; seeds and reference assets are listed separately, and the English originals are preserved verbatim, not replaced with translated text as actual input.

### English text generation (`t2va-5s`)

No reference assets; seed `1101`. Corresponds to the 5-second English baseline; concurrency 1/2/4 reuse the same prompt.

> A small red toy car rolls across a wooden table and stops beside a blue cube. The wheels rattle softly, then the room becomes quiet.

### Chinese text generation (`t2va-zh-5s`)

No reference assets; seed `1104`. Corresponds to the Chinese scene test, not a word-for-word dialogue or lip-sync test.

> Fixed camera. A red toy car slowly drives across a wooden table and stops beside a blue cube. The wheels make a soft rattling sound; after it stops, the room becomes quiet. Keep the toy car’s appearance consistent, with no camera cuts.

### First/last frame control (`fl2va-both`)

Seed `2103`; the first and last frames of the toy car illustration are passed in, with the character being `keyframe` in both, and frame positions at `0` and `-1` respectively. Corresponds to the first/last frame comparison image.

> A red toy car rolls slowly to the right across the wooden table and stops beside the blue cube. Keep the camera fixed and the simple illustrated style. Soft wheel rattling, then silence.

### Mixed image, video, and audio reference (`ref2va-mixed`)

Seed `3106`; the three inputs are a red car reference image, a 5-second silent action video, and a 5-second dual-channel WAV, with the character being `reference` in all three. Corresponds to the mixed reference comparison image.

> Use &lt;Picture 1&gt; as the subject, &lt;Video 1&gt; as the motion reference, and &lt;Audio 1&gt; as the sound reference. The red toy car rolls to the right across the wooden table with soft rhythmic tones.

In the mixed reference, `<Picture 1>`, `<Video 1>`, and `<Audio 1>` point to the first asset of the corresponding type in the request, not local file paths; reproduction requires submitting the image, video, and audio together, not just copying this text. First/last frames likewise require accompanying images. Fixed seeds facilitate comparison but do not guarantee pixel-identical generation across engines.

These prompts contain subject, motion, and sound requirements simultaneously; the Chinese sample also specifies a fixed camera. They are test inputs, not a claim that "all requirements are satisfied"; actual performance should be viewed together with the frame extraction and acceptance results below.

[Download the full test case JSON](../../assets/practices/minimax-h3-h20/test-cases.json), containing all 13 input categories with their corresponding seeds, durations, and reference asset relationships; the 5-second English input is tested at concurrency 1/2/4, forming 15 configuration categories per engine. `/fixtures` in the JSON is the in-container asset mount path; reproduction requires providing the corresponding assets.

<!-- MEASURED_RESULTS_START -->
## Measured results

The SGLang text generation and first/last frame matrix is complete. "Success" below means the request and media acceptance passed; visual and audio semantic quality must be checked separately. Reference asset and vLLM fix re-test results appear later, with each version listed separately.

| Configuration | Formal success count | Median (s) | Range (s) | Videos/hour including verification |
| --- | ---: | ---: | --- | ---: |
| Text generation, 5 s, concurrency 1 | 3/3 | 315.631 | 315.628–315.634 | 11.394 |
| Chinese text generation, 5 s, concurrency 1 | 1/1 | 315.632 | 315.632–315.632 | 11.393 |
| Text generation, 10 s, concurrency 1 | 3/3 | 938.854 | 938.798–938.905 | 3.832 |
| Text generation, 15 s, concurrency 1 | 3/3 | 1866.757 | 1866.725–1866.766 | 1.927 |
| Text generation, 5 s, concurrency 2 | 6/6 | 473.624 | 315.799–631.454 | 11.397 |
| Text generation, 5 s, concurrency 4 | 12/12 | 788.422 | 315.844–1261.569 | 11.413 |
| First frame control, 5 s | 3/3 | 342.766 | 342.762–342.771 | 10.494 |
| Last frame control, 5 s | 3/3 | 342.764 | 342.762–342.852 | 10.493 |
| First/last frame control, 5 s | 3/3 | 371.847 | 371.842–372.845 | 9.666 |

[Download per-sample raw values and file summary CSV](../../assets/practices/minimax-h3-h20/sglang-fl2va-results.csv). The 10-second configuration excluded original samples affected by other requests/brief model loading and used independent supplementary runs instead, totaling 3 valid formal samples.

Concurrency 2/4 all succeeded, but throughput remains approximately 11.4 videos/hour, with end-to-end median increasing with queueing. This set of results cannot be interpreted as concurrent requests bringing a corresponding multiple of inference throughput improvement.

The warm-up for the 5-second English, concurrency 1 configuration was 316.670 seconds, not counted in the table. All four files decoded completely: 1344 × 768, 124 frames, 24 fps,
video actual duration 5.166667 seconds, AAC dual-channel 32 kHz audio track. MP4 container duration is 5.175 seconds; RTF calculated on video duration is approximately **61.09**.
The 50 sampling points correspond to 49 DiT executions in the logs. The four MP4s with fixed seeds are byte-identical, with SHA-256
`35aa8dee4653c77ddbb6255f2b35c9758918379b5f97faa70ae9d6ca9b3434b8`.

Within the request time windows of these three formal samples, the four-card NVML sampling peak was **94.51–96.07 GiB/card**,
and the per-card power sample mean was **329.17–338.22 W**. Startup and warm-up are excluded here; the server-side reported
`peak_memory_mb` is not the same measurement basis. Each time window covers approximately 313.58–313.92 seconds,
with a maximum sampling gap of approximately 1.52 seconds, so the GPU memory figures are discrete sampling peaks and do not represent capture of all instantaneous spikes.

<video controls preload="metadata" style="width:100%;max-width:960px" poster="../../../assets/practices/minimax-h3-h20/sglang-t2va-5s-poster.png">
  <source src="../../assets/practices/minimax-h3-h20/sglang-t2va-5s.mp4" type="video/mp4">
</video>

[Download the untranscoded original MP4](../../assets/practices/minimax-h3-h20/sglang-t2va-5s.mp4) to re-check both picture and audio track simultaneously.

![Six actual frames from the SGLang 5-second English warm-up video](../../assets/practices/minimax-h3-h20/sglang-t2va-5s-contact-sheet.png)

Frame-by-frame inspection shows the red toy car stopping after approaching the blue cube, with the subject's appearance remaining consistent. This is a visual check of actual output, not an independent human rating.
The decoded audio track has an RMS of approximately −45.88 dBFS and a peak of approximately 0.307, proving the presence of a finite, non-all-zero signal;
these values cannot prove audio semantic correctness or audio-video synchronization, and listening quality cannot yet be marked as passed based on them.

The Chinese use case also completed warm-up and one formal generation (315.632 seconds, 124 frames). In the frame-by-frame results, the small car stops after approaching the blue block, but the blue block's position in the frame also visibly shifts, which does not fully match the "fixed camera" requirement. This is therefore recorded as interface and media structure passing, with the fixed-camera instruction only partially unmet; a successfully returned file is not treated as evidence that all instructions were followed. These Chinese and English use cases test scene prompts and ambient audio, and cannot be used to evaluate multilingual dialogue, lip sync, or the effect of a fully hosted system.

For first-frame, last-frame, and first-and-last-frame control, six frames were sampled from the first formal sample of each: the red car moves to the right and stops beside the blue block, the illustration appearance remains consistent, and the constrained endpoints match the input object positions. The mean absolute error of the four constrained endpoints against the original image's RGB pixels is 3.16–3.55 (on a 0–255 scale); this is only a file-level comparison, not a general perceptual quality score, and does not imply pixel-perfect lossless restoration.

![Actual six-frame results of first-and-last-frame control](../../assets/practices/minimax-h3-h20/sglang-fl2va-both-contact-sheet.png)

![Actual frames from both engines with identical first-and-last-frame input](../../assets/practices/minimax-h3-h20/keyframe-output-comparison.png)

The comparison images use the first formal sample from each engine, with seed 2103, identical prompts, and identical input images. The endpoint compositions are close to the input, while the car position at the temporal midpoint differs; the durations shown in the images are for a single sample, not the median of three runs. [Frame extraction source and original video hashes](../../assets/practices/minimax-h3-h20/keyframe-output-comparison.json)

The 15-second sample actually decodes to 362 frames. The sailboat and sunset water scene in the extracted frames remain coherent, but the "paper" material mentioned in the prompt cannot be confirmed from these frames. The above spot checks are AI visual review; the complete audio tracks have been retained, but no independent listening-based semantic or audio-visual synchronization scoring has been completed.
<!-- VLLM_ORIGINAL_RESULTS_START -->
### vLLM-Omni original version generation results (interface acceptance not passed)

The following nine generation configurations produced 37 formal samples that passed request and media structure validation. Subsequent abnormal-request validation failed, so the overall stage remains FAIL; these performance figures do not indicate that the service has passed full acceptance.

| Configuration | Formal successes | Median (s) | Range (s) | Validated videos/hour |
| --- | ---: | ---: | --- | ---: |
| Text generation, 5 s, concurrency 1 | 3/3 | 329.892 | 329.592–329.932 | 10.905 |
| Chinese text generation, 5 s, concurrency 1 | 1/1 | 329.992 | 329.992–329.992 | 10.898 |
| Text generation, 10 s, concurrency 1 | 3/3 | 965.606 | 965.264–965.692 | 3.725 |
| Text generation, 15 s, concurrency 1 | 3/3 | 1907.032 | 1906.861–1908.529 | 1.886 |
| Text generation, 5 s, concurrency 2 | 6/6 | 494.771 | 332.914–656.845 | 10.961 |
| Text generation, 5 s, concurrency 4 | 12/12 | 821.909 | 332.064–1309.943 | 11.001 |
| First-frame control, 5 s | 3/3 | 358.773 | 358.328–359.248 | 10.027 |
| Last-frame control, 5 s | 3/3 | 359.438 | 358.496–359.596 | 10.016 |
| First-and-last-frame control, 5 s | 3/3 | 389.580 | 389.225–389.713 | 9.236 |

[Download original version per-sample CSV data](../../assets/practices/minimax-h3-h20/vllm-fl2va-original-results.csv). Warm-up is excluded, and the post-fix rerun is not mixed into this table.

The original version's concurrency 1/2/4 throughput is approximately 10.9–11.0 videos/hour, with queueing increasing request latency. This run window spans different co-located loads on the same host, including SGLang stress testing, sample creation, and another engine stopping, so it cannot be used to produce an interference-free dual-engine performance ranking.

<!-- VLLM_ORIGINAL_RESULTS_END -->

### vLLM-Omni post-fix retest

The original version's 37 generation records are retained in the table above. The five configuration types retested after the fix are as follows: four types of invalid input returned 400, and the subsequent valid generations also passed; the final summary uses the fixed results for these configurations and does not mix the old and new rounds into a single distribution.

| Configuration | Formal successes | Median (s) | Range (s) | Validated videos/hour |
| --- | ---: | ---: | --- | ---: |
| 5 s, concurrency 2 | 6/6 | 494.276 | 332.243–656.079 | 10.972 |
| 5 s, concurrency 4 | 12/12 | 822.192 | 332.307–1309.161 | 11.000 |
| First-frame control | 3/3 | 359.106 | 357.793–360.091 | 10.021 |
| Last-frame control | 3/3 | 359.061 | 357.826–359.363 | 10.028 |
| First-and-last-frame control | 3/3 | 389.115 | 389.006–391.270 | 9.230 |

### Final results for the six types of reference input

Each cell below is the end-to-end median of 3 valid formal generations, with 5-second output, 1344 × 768, 24 fps, 50 sampling steps, concurrency 1; warm-up is not counted. A total of 36 formal generations across both engines passed request and media structure checks.

| Reference input | SGLang (s) | vLLM-Omni (s) |
| --- | ---: | ---: |
| Single image | 532.166 | 553.630 |
| Three images | 1114.354 | 1164.995 |
| Silent video | 980.119 | 1009.945 |
| Video with audio | 995.101 | 1016.897 |
| Image + audio | 542.437 | 562.071 |
| Image + video + audio | 1340.278 | 1371.531 |

SGLang's first three types use the original version, and the three types with audio use the context-fix patch; all six vLLM types use the error-propagation fix version. vLLM's single-image case still loads from NVMe on the original node, while the other five types load directly from CFS on the new H20-3e node. The numbers in the table are for capacity and latency reference; the differences cannot be attributed entirely to the engines.

Multi-image and video references significantly increase generation time for this workload group: vLLM with three images takes about 19 minutes 25 seconds, and with mixed references about 22 minutes 52 seconds, both generating a roughly 5-second video. These fixed materials do not yet constitute an evaluation set for character consistency or reference voice timbre fidelity; full decode passing does not mean that reference relationships and all semantic instructions were followed.

![Actual frames from both engines with identical mixed reference input](../../assets/practices/minimax-h3-h20/mixed-output-comparison.png)

The comparison images use the same image, action video, audio, and seed 3106, taking the first formal sample from each. The extracted frames show a red car moving to the right in both, along with regenerated window shadows and desktop; composition, car body proportions, and positions at the same moment differ. This is visual observation only and does not evaluate reference audio reproduction or full motion quality. [Frame extraction source and original video hashes](../../assets/practices/minimax-h3-h20/mixed-output-comparison.json)

![Concurrent throughput and waiting under the same workload](../../assets/practices/minimax-h3-h20/throughput.png)

In the figure, SGLang is the original version; vLLM concurrency 1 is the original version, and 2/4 are post-fix retest values. Shared host load differs, and the point of the figure is that each engine's throughput does not double with concurrency; it cannot be used for strict engine ranking.

<!-- MEASURED_RESULTS_END -->

## How audio-visual artifacts are retained

### Page and exception recovery

SGLang returns HTTP 400 with a clear reason for four request types: 99-second duration, empty prompt, corrupted image bytes, and missing reference material. Valid requests were then actually submitted through the light-themed page, completing generation, browser playback to the end, and download by clicking. The downloaded MP4's SHA-256 matches the file retained on the server. The player is not muted and the audio track is present, but this does not replace listening-based semantic evaluation.

![SGLang actual generation, playback, and download page](../../assets/practices/minimax-h3-h20/sglang-ui.jpg)

The roughly 415 seconds shown on the page include queueing wait for a preceding Chinese feature request; the page acceptance sample does not enter the performance master table.

### Original artifact retention

Service logs, per-second GPU memory/power, request JSON, original MP4s, and media check results are all written to persistent hostPath. Different engine and model partitions use separate subdirectories. Each batch is compared by file byte count and SHA-256 through the local upload-back tool; scaling down only releases compute resources.

The fixed SGLang version deletes outputs that fail final media validation. This run uses a small patch protected by the original source SHA-256 that changes this deletion action to recording the retention path; the validation-failure status and inference logic retain their original semantics. The patch and run scripts are archived with the experiment. vLLM synchronous responses are written directly to the persistent directory by the shared client running inside the test Pod.

Success criteria include: the MP4 actually decodes completely, with an H.264 video stream, 24 fps, AAC dual-channel 32 kHz audio track, and expected dimensions and duration. A file that decodes only proves the media structure is valid; subject consistency, motion, instruction following, audio-visual synchronization, and first-and-last-frame control are recorded separately.

## Reproduction materials

Repository [`examples/minimax-h3-h20`](https://github.com/runzhliu/aik8s/tree/main/examples/minimax-h3-h20)
stores the launcher, deployment manifest generator, test material generator, shared client, matrix executor, and upload-back validation tool. Images use fixed digests, dependencies are installed at build time, and no models or evaluators are downloaded during offline runtime.

```bash
python3 render_deployment.py \
  --engine sglang \
  --image '<REGISTRY>/vip/llm-serving-sglang-diffusion@sha256:<DIGEST>' \
  --namespace aik8s-ms --node '<H20_NODE>' \
  --nvme-path /srv/models/MiniMax-H3/v1 \
  --output-host-path /srv/h3-results/sglang-fl2va \
  --fixtures-host-path /srv/h3-results/fixtures > deployment.json
```

The generator defaults to zero replicas. After the source-target consistency check completes and the model snapshot identifier and completion marker are written, startup proceeds on the selected node. The four GPUs must be formally allocated by Kubernetes; inference must not be run directly in a preflight container that has not requested GPUs.

## Four-GPU deployment advice: check connectivity first, then utilization

The H3 four-GPU configuration requires multi-GPU cooperation for encoding, diffusion, and decoding. After obtaining four GPUs, you should also confirm how they are interconnected and the distance to CPU and memory. High GPU utilization does not mean there is no bottleneck in communication or data movement.

**First verify the four GPUs actually allocated to the container.** The four allocated GPUs on this round's initial node show `NV18` pairwise, indicating a connection composed of 18 NVLinks; this is topology information, not measured communication bandwidth. During deployment, use GPU UUIDs to cross-check container and host allocation results, and inspect NVLink/P2P paths; do not infer identical connectivity from "same machine" or adjacent numbering alone. [NVIDIA documentation](https://docs.nvidia.com/deploy/nvidia-smi/index.html)

**Then check NUMA affinity.** When CPU threads, host memory pages, and GPUs are distributed across different NUMA domains, some memory accesses or CPU–GPU data movement may cross sockets, adding latency and bandwidth contention. You need to cross-check GPU CPU/NUMA affinity, the CPUs and memory nodes allowed for the container, and the placement of encoding, data preparation, and communication threads.

You can check inside the actual inference container:

```bash
# GPU 连接，以及 CPU/NUMA affinity
nvidia-smi topo -m

# 对照实际 GPU UUID 与型号
nvidia-smi --query-gpu=uuid,name --format=csv

# 容器实际允许使用的 CPU 与内存节点
cat /proc/self/status
# 重点查看 Cpus_allowed_list、Mems_allowed_list
```

Do not bind the entire four-GPU process directly to NUMA 0. If the four GPUs themselves span NUMA, one-sided CPU pinning or memory pinning may make the GPUs on the other side farther away. Affinity arrangements should be made per rank, combining each rank's GPU, CPU threads, and memory allocation; GPUs connected via NVLink does not mean host-side NUMA effects automatically disappear.

In Kubernetes, `nvidia.com/gpu: 4` only expresses resource quantity and cannot by itself guarantee affinity between four GPUs and CPU/memory. The device plugin must provide topology information, combined with Topology Manager, CPU Manager, and the corresponding memory policy configuration. `single-numa-node` requires resources to be alignable within a single NUMA node; when hardware cannot satisfy this, admission may be rejected, and it must not be enabled indiscriminately just to get a four-GPU Pod scheduled. [Official documentation](https://kubernetes.io/docs/tasks/administer-cluster/topology-manager/)

Before going live, a two-step acceptance is recommended:

1. **Check communication paths.** Run NCCL tests on the same four GPUs with the same container limits, covering the communication types and representative data volumes actually used by the inference topology; check whether NVLink/P2P is available, whether unexpected fallback occurs, and record bandwidth and duration. A single small-data all-reduce run is not enough to characterize communication behavior across all generation stages.
2. **Retest real generation.** Fix the model, prompt, precision, seed, concurrency, and GPU allocation, then compare end-to-end latency and throughput before and after adjustments. Change only one item at a time, such as NUMA affinity or CPU thread count, to avoid mistaking compilation warm-up or co-located host load changes for optimization gains.

Troubleshooting methods for container shared memory, P2P, and system settings are in [NCCL Troubleshooting](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/troubleshooting.html).

This round did not complete a controlled "same-NUMA vs. cross-NUMA" experiment, so no figures are reported for how much slower cross-NUMA is or how much faster CPU pinning can be. The above is a verification method for four-GPU service deployment; performance gains must be confirmed by same-condition retests on the target node.
