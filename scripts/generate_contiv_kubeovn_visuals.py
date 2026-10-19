#!/usr/bin/env python3
"""Render an explicitly labelled report from public, anonymized observations.

Input contains allowlisted archived values, not raw cluster exports. This creates
a record visualization, never a simulated product UI or monitoring screenshot.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets/practices/contiv-to-kubeovn-underlay"


def font(size, bold=False):
    name = "Arial Bold.ttf" if bold else "Arial.ttf"
    candidates = [
        Path("/System/Library/Fonts/Supplemental") / name,
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("Install Arial or DejaVu Sans before rendering")


def main():
    source = ASSETS / "acceptance-evidence.json"
    data = json.loads(source.read_text())
    final = data["rejoined_stage"]
    checks = final["node_acceptance"]
    passed = sum(row["passed"] for row in checks)
    scopes = final["scope_checks"]
    total_scope = sum(row["total"] for row in scopes.values())
    passed_scope = sum(row["passed"] for row in scopes.values())
    assert passed == len(checks) == 12
    assert passed_scope == total_scope == 22
    assert final["ssh_successes"] + final["ssh_failures"] == final["ssh_samples"]

    image = Image.new("RGB", (1200, 675), "#f6f8fd")
    draw = ImageDraw.Draw(image)
    ink, muted, blue, green = "#24324c", "#63738e", "#3158df", "#14776b"

    def text(x, y, content, size=24, fill=ink, bold=False, max_width=None):
        face = font(size, bold)
        box = draw.textbbox((0, 0), content, font=face)
        width = box[2] - box[0]
        if max_width is not None and width > max_width:
            raise ValueError(f"Text exceeds its column: {content}")
        if x + width > 1150:
            raise ValueError(f"Text exceeds safe area: {content}")
        draw.text((x, y), content, fill=fill, font=face)

    text(52, 34, "Contiv to Kube-OVN: one node rejoined", 37, bold=True)
    text(52, 88, "Archived acceptance record  |  Kubernetes 1.30.4  /  Kube-OVN 1.16.12", 22, fill=muted)

    stats = [
        ("NODE STATE", "READY", green),
        ("POD IPs / RESERVED IPs", f'{final["allocated_addresses"]} / {final["reserved_addresses"]}', blue),
        ("NODE-LOCAL CHECKS", f"{passed} / {len(checks)}", blue),
    ]
    for i, (label, value, color) in enumerate(stats):
        x = 52 + i * 372
        draw.rounded_rectangle((x, 140, x + 352, 281), radius=15, fill="white", outline="#d6dfef", width=2)
        text(x + 22, 159, label, 19, muted, max_width=308)
        text(x + 22, 198, value, 48, color, bold=True)

    for x in (52, 610):
        draw.rounded_rectangle((x, 310, x + 538, 532), radius=15, fill="white", outline="#d6dfef", width=2)
    text(76, 328, "ISOLATION VERIFIED", 22, bold=True)
    text(76, 370, f"API / RBAC / admission: {passed_scope} / {total_scope}", 25, green, max_width=490)
    text(76, 412, "Other-node OVN annotation changes: 0", 23, max_width=490)
    text(76, 453, "Original Cilium template: unchanged", 23, max_width=490)

    text(634, 328, "RESULT BOUNDARIES", 22, bold=True)
    text(634, 370, "Old / new Pod-IP HTTP: bidirectional", 24, green, max_width=490)
    text(634, 412, f'SSH fresh-auth probes: {final["ssh_successes"]} / {final["ssh_samples"]}', 24, max_width=490)
    text(634, 453, "Service / DNS: not tested after rejoin", 23, max_width=490)

    text(52, 557, "1 SSH probe failed; uninterrupted access was not established.", 24, fill="#9a5a1b")
    text(52, 607, "Anonymized observations. Record visualization, not a live dashboard screenshot.", 21, fill=muted)
    output = ASSETS / "acceptance-record.png"
    image.save(output, optimize=True)
    manifest = {
        "purpose": "Archive summary; not a monitoring screenshot",
        "size": [1200, 675],
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "generator": "scripts/generate_contiv_kubeovn_visuals.py",
        "output": output.name,
        "labels_language": "en",
        "article_languages": ["zh", "en"],
        "diagram_sources": "Editable Mermaid blocks in both article sources",
        "privacy": "Only allowlisted anonymized records; no original IP, MAC, VLAN, hostname, credentials or private file paths",
    }
    (ASSETS / "visual-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
