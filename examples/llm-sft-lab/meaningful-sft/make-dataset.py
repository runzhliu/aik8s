#!/usr/bin/env python3
"""Generate template-family-isolated train, validation, and blind-test data."""

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """你是 OpsRoute 故障分诊器。请使用训练中学到的组织内部故障码，只返回一个 JSON 对象，不要输出 Markdown、解释或思考过程。必须包含 diagnosis_code、conclusion、evidence、next_action、needs_more_evidence、prohibited_action 六个字段；evidence 必须是字符串数组，needs_more_evidence 必须是布尔值。只能根据已给证据判断，信息不足时使用对应的未知分类。"""


CATEGORIES: list[dict[str, Any]] = [
    {
        "code": "SCH-101",
        "title": "GPU 容量不足",
        "action": "核对 Pod 的 GPU 请求量、节点可分配量和其他工作负载已占用量。",
        "prohibited": "不要通过反复重启 Pod 解决容量不足。",
        "keyword": "重启",
        "train": [
            "Pod {job} 的 FailedScheduling 事件为：0/{nodes} nodes are available，{nodes} Insufficient nvidia.com/gpu。",
            "调度器显示 {job} 请求 {gpu} 张 GPU，但所有候选节点剩余 GPU 都小于请求量。",
            "PodCondition=Unschedulable，唯一失败原因是扩展资源 nvidia.com/gpu 不足。",
        ],
        "validation": [
            "资源快照显示每个候选节点最多空闲 1 张卡，而 {job} 必须在单节点申请 {gpu} 张。",
        ],
        "test": [
            "调度约束全部匹配，但 GPU allocatable 减去已请求量仍小于 {job} 的 GPU request。",
            "事件只报告 GPU 资源无法满足；CPU、内存、PVC、亲和性和污点检查均通过。",
        ],
    },
    {
        "code": "SCH-102",
        "title": "节点选择或亲和性不匹配",
        "action": "对照 Pod 的 nodeSelector/requiredDuringScheduling 与节点真实标签。",
        "prohibited": "不要为了调度成功而直接删除生产节点标签。",
        "keyword": "标签",
        "train": [
            "FailedScheduling 显示 {nodes} node(s) didn't match Pod's node affinity/selector。",
            "{job} 要求 accelerator=l20，但有空闲 GPU 的节点标签是 accelerator=t4。",
            "Pod 的 requiredDuringScheduling 条件没有任何 Ready 节点能够同时满足。",
        ],
        "validation": [
            "GPU 数量足够，但候选节点均因硬性 nodeAffinity 表达式被过滤。",
        ],
        "test": [
            "调度器谓词结果只有 NodeAffinity failed，资源余量和污点容忍均正常。",
            "工作负载限定 zone={zone}，空闲 GPU 实际只存在于另一个 zone。",
        ],
    },
    {
        "code": "SCH-103",
        "title": "污点未被容忍",
        "action": "核对节点 NoSchedule/NoExecute 污点与 Pod tolerations 是否精确匹配。",
        "prohibited": "不要在未确认隔离目的前移除节点污点。",
        "keyword": "污点",
        "train": [
            "事件为 {nodes} node(s) had untolerated taint {{dedicated: gpu}}。",
            "GPU 节点存在 quarantine=serving:NoSchedule，而 {job} 没有对应 toleration。",
            "资源和标签都满足，Pod 最终被未容忍的 NoSchedule taint 拒绝。",
        ],
        "validation": [
            "候选节点带有 team=research:NoSchedule，工作负载 tolerations 列表为空。",
        ],
        "test": [
            "调度事件明确指出 taint 未被 toleration 覆盖，其他过滤条件均通过。",
            "{job} 被隔离节点的 NoExecute 规则排除，PodSpec 中找不到匹配容忍项。",
        ],
    },
    {
        "code": "QUE-201",
        "title": "队列配额不足",
        "action": "检查队列 capability、allocated、request 和准入状态，再决定排队或调整配额。",
        "prohibited": "不要绕过队列直接提高工作负载优先级。",
        "keyword": "优先级",
        "train": [
            "作业 {job} 保持 Inqueue，Queue {queue} 的 allocated 加本次 request 已超过 capability。",
            "节点存在空闲卡，但队列配额中 nvidia.com/gpu 的剩余额度为 0。",
            "准入控制拒绝此次申请，原因是所属队列 GPU quota exhausted。",
        ],
        "validation": [
            "PodGroup 尚未 Admit，队列状态显示 request 超过 guarantee 与可借用上限。",
        ],
        "test": [
            "物理集群有余量，然而队列账本的 GPU 可用额度不足以接纳 {job}。",
            "调度前的 queue admission 已失败，尚未进入节点过滤阶段。",
        ],
    },
    {
        "code": "QUE-202",
        "title": "Gang 最小成员无法同时满足",
        "action": "核对 PodGroup minMember、各成员资源请求和可同时调度的节点容量。",
        "prohibited": "不要让部分 Worker 长时间占卡等待其余 Rank。",
        "keyword": "Worker",
        "train": [
            "PodGroup {job} 要求 minMember={member}，当前最多只能同时放置 {available} 个成员。",
            "已有部分 Worker 可调度，但 Gang 条件未达到，整个作业没有被 Admit。",
            "调度器报告 insufficient resources to meet minAvailable of PodGroup。",
        ],
        "validation": [
            "分布式作业需要 {member} 个 Rank 一起启动，集群只能为其中 {available} 个预留资源。",
        ],
        "test": [
            "单个 Pod 都可放置，但找不到能一次性满足整个 PodGroup 最小成员数的组合。",
            "作业卡在 Gang admission；minAvailable={member}，可并发调度成员只有 {available}。",
        ],
    },
    {
        "code": "STO-301",
        "title": "PVC 尚未绑定",
        "action": "检查 PVC 状态、StorageClass、访问模式、容量和卷绑定事件。",
        "prohibited": "不要在未备份数据前删除 PVC 或 PV。",
        "keyword": "删除",
        "train": [
            "FailedScheduling 报告 pod has unbound immediate PersistentVolumeClaims，PVC {pvc} 为 Pending。",
            "{job} 引用的 PVC {pvc} 没有 Bound，卷绑定事件显示找不到匹配 PV。",
            "GPU 资源已满足，但 VolumeBinding 插件拒绝了该 Pod。",
        ],
        "validation": [
            "工作负载尚未创建容器，调度阶段唯一阻塞项是未绑定的持久卷声明。",
        ],
        "test": [
            "调度器的 VolumeBinding 检查失败；所需 claim 仍处于 Pending。",
            "Pod 引用 {pvc}，其 StorageClass 和可用 PV 无法完成绑定。",
        ],
    },
    {
        "code": "IMG-401",
        "title": "容器镜像拉取失败",
        "action": "查看镜像地址、Tag/Digest、拉取凭证和节点到镜像仓库的连通性。",
        "prohibited": "不要把长期凭证直接写进 PodSpec 或日志。",
        "keyword": "凭证",
        "train": [
            "Pod 已调度到节点，但容器状态为 ImagePullBackOff，事件包含 unauthorized。",
            "{job} 的 Waiting reason=ErrImagePull，节点返回 manifest unknown。",
            "Kubelet 无法拉取镜像，错误为 connection timeout to registry。",
        ],
        "validation": [
            "调度已经完成，容器创建前持续出现 Back-off pulling image。",
        ],
        "test": [
            "Pod 有 nodeName，GPU 也已分配，但镜像下载阶段因认证失败而等待。",
            "容器未启动的直接原因是仓库中找不到指定 digest，而不是调度失败。",
        ],
    },
    {
        "code": "RUN-501",
        "title": "训练过程 CUDA OOM",
        "action": "记录 OOM 阶段与峰值显存，优先降低序列长度或 Micro Batch 并复测。",
        "prohibited": "不要只依靠清理缓存掩盖稳定复现的 OOM。",
        "keyword": "缓存",
        "train": [
            "训练进入 forward 后报 CUDA out of memory，尝试申请 {memory} MiB 失败。",
            "{job} 已开始运行，在 backward 阶段因 GPU memory exhausted 退出。",
            "日志显示 reserved 与 allocated 接近显存上限，并抛出 torch.OutOfMemoryError。",
        ],
        "validation": [
            "模型加载成功，首个长样本计算时显存达到上限并发生 CUDA OOM。",
        ],
        "test": [
            "Pod 完成调度和镜像拉取，训练 Step 内因无法再分配显存而终止。",
            "缩短输入后可运行，恢复原序列长度便稳定触发 torch.cuda.OutOfMemoryError。",
        ],
    },
    {
        "code": "NET-601",
        "title": "NCCL 跨节点通信失败",
        "action": "核对各 Rank 地址、网卡选择、防火墙与 NCCL Transport 日志。",
        "prohibited": "不要只增加超时时间而忽略实际网络错误。",
        "keyword": "超时",
        "train": [
            "多机训练初始化时报 NCCL WARN socketStartConnect: Connect to {peer} failed。",
            "Rank {rank} 在 init_process_group 后等待，远端 Rank 日志出现 connection refused。",
            "单机训练正常，跨节点 Collective 报 ncclSystemError 和网络不可达。",
        ],
        "validation": [
            "所有模型都已加载，但第一个跨机 AllReduce 无法建立连接。",
        ],
        "test": [
            "故障只在多节点出现，NCCL bootstrap 日志显示 peer address 连接失败。",
            "两个 Rank 均已启动，集合通信阶段报告 remote process exited 或 network error。",
        ],
    },
    {
        "code": "DAT-701",
        "title": "SFT 数据格式或模板错误",
        "action": "抽样检查数据 Schema、角色顺序、Chat Template 和 Assistant Loss Mask。",
        "prohibited": "不要跳过坏样本继续训练并假设 Loss 仍然可信。",
        "keyword": "坏样本",
        "train": [
            "数据预处理在训练前失败：样本缺少 messages 字段或 assistant 角色。",
            "{job} 的 Dataset map 抛出 KeyError: messages，GPU 尚未开始计算。",
            "Tokenize 后所有 labels 都是 -100，Assistant Loss Mask 没有覆盖回答。",
        ],
        "validation": [
            "训练进程能加载模型，但在构造 Chat Template 时报告 role sequence invalid。",
        ],
        "test": [
            "错误发生在数据编码阶段，某些记录把 assistant 写成了 answer 字段。",
            "首步之前数据校验失败，日志指出对话角色顺序和模板要求不一致。",
        ],
    },
    {
        "code": "UNC-000",
        "title": "证据不足，暂不能归因",
        "action": "先补充 Pod 状态、Events、相关控制器状态和失败时间窗口内日志。",
        "prohibited": "不要在没有事件和日志证据时直接重启或修改配置。",
        "keyword": "证据",
        "needs_more": True,
        "train": [
            "用户只说 {job} 失败了，没有提供状态、Events、日志或最近变更。",
            "当前信息只有“任务不正常”，无法区分调度、镜像、运行时、存储或网络问题。",
            "只有一张无时间戳的页面截图，关键错误信息不可见。",
        ],
        "validation": [
            "请求立即给出根因，但没有任何可验证的报错、事件或指标。",
        ],
        "test": [
            "现有描述仅为“训练挂了，请修复”，除此之外没有上下文。",
            "没有 Pod 名称、时间范围、状态或日志，却要求直接判断是哪一层故障。",
        ],
    },
]


QUESTIONS = [
    "请按平台规范完成分诊。",
    "应该先检查什么？只返回规定的 JSON。",
    "有人建议直接重启，请根据证据给出结构化结论。",
    "请给出故障码、证据和下一步动作。",
]

NEUTRAL_CONTEXT = [
    "采样时间窗口为最近五分钟。",
    "需要保留原始证据以便复盘。",
    "未执行人工驱逐或强制重启。",
    "请求使用统一分诊格式记录。",
]

SPLIT_CONFIG = {
    "train": (30, 20260820),
    "validation": (5, 20260821),
    "test": (10, 20260822),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def format_values(rng: random.Random, index: int) -> dict[str, Any]:
    member = rng.choice([4, 8, 16])
    return {
        "job": f"train-{index:04d}",
        "nodes": rng.choice([4, 8, 12]),
        "gpu": rng.choice([2, 4, 8]),
        "zone": rng.choice(["zone-a", "zone-b", "zone-c"]),
        "queue": rng.choice(["research", "batch", "training"]),
        "member": member,
        "available": rng.choice([1, 2, max(1, member - 1)]),
        "pvc": f"dataset-{index:04d}",
        "memory": rng.choice([256, 512, 1024, 2048]),
        "peer": f"10.0.{rng.randrange(1, 32)}.{rng.randrange(2, 250)}:29500",
        "rank": rng.choice([0, 1, 2, 3]),
    }


def target_for(category: dict[str, Any], evidence: str) -> dict[str, Any]:
    return {
        "diagnosis_code": category["code"],
        "conclusion": category["title"],
        "evidence": [evidence],
        "next_action": category["action"],
        "needs_more_evidence": category.get("needs_more", False),
        "prohibited_action": category["prohibited"],
    }


def make_split(split: str) -> list[dict[str, Any]]:
    count_per_category, seed = SPLIT_CONFIG[split]
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for category_index, category in enumerate(CATEGORIES):
        templates = category[split]
        for sample_index in range(count_per_category):
            global_index = category_index * count_per_category + sample_index
            values = format_values(rng, global_index)
            evidence = templates[sample_index % len(templates)].format(**values)
            user = f"作业：{values['job']}。观察：{evidence} {rng.choice(NEUTRAL_CONTEXT)} {rng.choice(QUESTIONS)}"
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ]
            target = target_for(category, evidence)
            row: dict[str, Any] = {
                "id": f"{split}-{category['code']}-{sample_index:03d}",
                "messages": messages,
            }
            if split == "test":
                row["gold"] = {
                    "diagnosis_code": category["code"],
                    "needs_more_evidence": category.get("needs_more", False),
                    "prohibited_keyword": category["keyword"],
                }
            else:
                row["messages"] = messages + [
                    {
                        "role": "assistant",
                        "content": json.dumps(target, ensure_ascii=False, separators=(",", ":")),
                    }
                ]
            rows.append(row)
    rng.shuffle(rows)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"categories": len(CATEGORIES), "splits": {}}
    for split in SPLIT_CONFIG:
        rows = make_split(split)
        path = output_dir / f"{split}.jsonl"
        manifest["splits"][split] = {
            "path": str(path),
            "examples": len(rows),
            "sha256": write_jsonl(path, rows),
        }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "DATASET_MANIFEST", **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
