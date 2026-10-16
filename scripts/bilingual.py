"""Shared, deterministic checks for paired Chinese and English documentation."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGLISH = ROOT / "translations/en"
MANIFEST = ROOT / "translations/manifest.json"
HAN = re.compile(r"[\u3400-\u9fff]")
MARKER = re.compile(r"AIK8S_LITERAL_\d{5}_END")


class FunctionalHTML(HTMLParser):
    """Compare inline HTML behavior while allowing translated reader-facing labels."""
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        descriptive = {'alt', 'title', 'aria-label', 'placeholder', 'lang'}
        self.elements.append((tag, sorted((key, value) for key, value in attrs if key not in descriptive)))

    handle_startendtag = handle_starttag


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_pages(root: Path = ROOT) -> list[Path]:
    # Include new public articles, but honor .gitignore (private plans are excluded).
    result = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "docs"],
        cwd=root, text=True,
    )
    return sorted({root / p for p in result.splitlines() if p.endswith(".md")})


def ignored_targets(root: Path, names: list[str]) -> set[str]:
    """A local translation must also survive a clean Git checkout in CI."""
    paths = ['translations/en/' + name for name in names]
    if not paths:
        return set()
    result = subprocess.run(
        ['git', 'check-ignore', '--stdin'], input='\n'.join(paths) + '\n',
        cwd=root, text=True, capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError('could not check translation Git visibility')
    return {path.removeprefix('translations/en/') for path in result.stdout.splitlines()}


def protect(text: str) -> tuple[str, dict[str, str]]:
    """Freeze executable fixtures and link targets; Mermaid labels remain translatable."""
    saved: dict[str, str] = {}

    def save(value: str) -> str:
        key = f"AIK8S_LITERAL_{len(saved):05d}_END"
        saved[key] = value
        return key

    lines = text.splitlines(keepends=True)
    result, index = [], 0
    while index < len(lines):
        match = re.match(r"^\s*(`{3,}|~{3,})(.*)", lines[index])
        if match:
            start, fence = index, match.group(1)
            is_mermaid = match.group(2).strip().lower() == 'mermaid'
            index += 1
            while index < len(lines):
                if re.match(r"^\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$", lines[index]):
                    index += 1
                    break
                index += 1
            block = ''.join(lines[start:index])
            if is_mermaid:
                # Consume its closing fence too. Otherwise the closing ```
                # looks like an untyped opening fence and hides following prose.
                result.append(block)
            else:
                body = block.rstrip('\r\n')
                result.append(save(body) + block[len(body):])
        else:
            result.append(lines[index])
            index += 1
    output = "".join(result)
    # Inline code, Markdown link destinations and explicit heading IDs are literals.
    for pattern in [r"(`+)(?!`)([^\n]*?)(?<!`)\1", r"(?<=\]\()[^\n]*?(?=\))", r"\{\s*#[^}]+\}", r"https?://[^\s<>\])\"]+"]:
        output = re.sub(pattern, lambda m: save(m.group(0)), output)
    return output, saved


def restore(text: str, saved: dict[str, str]) -> str:
    for key, value in reversed(list(saved.items())):
        if text.count(key) != 1:
            raise ValueError(f"literal {key} occurs {text.count(key)} times; expected once")
        text = text.replace(key, value)
    if MARKER.search(text):
        raise ValueError("unresolved literal marker")
    return text


def mermaid_signatures(text: str) -> list[list[str]]:
    """Keep graph types, node shapes/IDs and edges while ignoring readable labels."""
    graphs = re.findall(r'^\s*```mermaid\s*\n(.*?)^\s*```\s*$', text, re.M | re.S)
    signatures = []
    for graph in graphs:
        sequence = graph.lstrip().startswith('sequenceDiagram')
        lines = []
        for raw in graph.splitlines():
            line = raw.strip()
            if not line or line.startswith('%%'):
                continue
            if sequence:
                line = re.sub(r'^(participant|actor)\s+(\S+)\s+as\s+.*$', r'\1 \2 as LABEL', line)
                line = re.sub(r':.*$', ':LABEL', line)
                line = re.sub(r'^(loop|alt|else|opt|par|and|critical|option|break)\s+.+$', r'\1 LABEL', line)
            else:
                line = re.sub(r'\[[^\]\n]*\]|\{[^}\n]*\}|\([^\)\n]*\)', lambda match: match.group()[0] + 'LABEL' + match.group()[-1], line)
                line = re.sub(r'\|[^|\n]*\|', '|LABEL|', line)
                line = re.sub(r'(-\.)[^.\n]+(\.->)', r'\1LABEL\2', line)
            lines.append(re.sub(r'\s+', '', line))
        signatures.append(lines)
    return signatures


def frontmatter_fields(text: str):
    if not text.startswith('---\n'):
        return {}, False
    match = re.match(r'---\n(.*?)\n---[ \t]*(?:\n|$)', text, re.S)
    if not match:
        return {}, True
    fields, name = {}, None
    for line in match.group(1).splitlines():
        field = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.*)$', line)
        if field:
            name = field.group(1)
            fields[name] = field.group(2)
        elif name:
            fields[name] += '\n' + line
    return fields, False


def structural_errors(source: str, target: str) -> list[str]:
    left, _ = protect(source)
    right, _ = protect(target)
    errors = []
    source_meta, source_bad = frontmatter_fields(source)
    target_meta, target_bad = frontmatter_fields(target)
    if source_bad or target_bad or set(source_meta) != set(target_meta):
        errors.append('front matter missing, malformed, or field names changed')
    else:
        for name, value in source_meta.items():
            if name == 'categories':
                # Category names are reader-facing labels; their list shape is metadata.
                items = lambda s: re.findall(r'^\s+-\s+.+$', s, re.M)
                if len(items(value)) != len(items(target_meta[name])):
                    errors.append('front matter category list structure changed')
            elif name not in ('title', 'description'):
                normalized = lambda s: re.sub(r'\s+', '', s.strip().strip('\"\''))
                if normalized(value) != normalized(target_meta[name]):
                    errors.append('non-prose front matter changed: ' + name)
            elif ': ' in target_meta[name] and not target_meta[name].startswith(('\"', "'", '>', '|')):
                errors.append('front matter scalar needs quotes: ' + name)
    headings = lambda s: re.findall(r"^(#{1,6})\s", s, re.MULTILINE)
    if headings(left) != headings(right):
        errors.append("heading levels/count changed")
    for line in target.splitlines():
        if re.match(r'^#{1,6}\s', line) and re.search(r'\{\s*#[^}]+\}\s*\S', line):
            errors.append('explicit heading ID must remain at the end of the heading')
            break
    if mermaid_signatures(source) != mermaid_signatures(target):
        errors.append('Mermaid graph topology or node shapes changed')
    tables = lambda s: len(re.findall(r"^\s*\|.*\|\s*$", s, re.MULTILINE))
    if tables(left) != tables(right):
        errors.append("Markdown table row count changed")
    table_columns = lambda s: [len(re.findall(r'(?<!\\)\|', row)) for row in re.findall(r'^\s*\|.*\|\s*$', s, re.M)]
    if table_columns(left) != table_columns(right):
        errors.append("Markdown table column structure changed")
    # Compare actual literal values, independent of marker numbering.
    _, a = protect(source)
    _, b = protect(target)
    from collections import Counter
    if Counter(a.values()) != Counter(b.values()):
        errors.append("code, URLs, link destinations or explicit anchors changed")
    original_html, translated_html = FunctionalHTML(), FunctionalHTML()
    original_html.feed(left)
    translated_html.feed(right)
    if original_html.elements != translated_html.elements:
        errors.append("inline HTML elements or functional attributes changed")
    if MARKER.search(target):
        errors.append("unresolved placeholders")
    prose = MARKER.sub("", right)
    chinese = len(HAN.findall(prose.replace("简体中文", "").replace("中文", "")))
    if chinese > max(8, len(HAN.findall(left)) * 0.01):
        errors.append(f"untranslated Chinese prose remains ({chinese} characters)")
    if len(right) < len(left) * 0.5:
        errors.append("translation is unexpectedly short")
    return errors


def read_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"schema_version": 1, "pages": {}}


def readme_errors(root: Path = ROOT, check_sync=True) -> list[str]:
    errors = []
    for name in ('README.md', 'README.en.md'):
        path = root / name
        if not path.exists():
            errors.append('missing repository ' + name)
        elif '[简体中文](README.md) | [English](README.en.md)' not in path.read_text():
            errors.append('missing reciprocal language links in ' + name)
    if check_sync and not errors:
        record_path = root / 'translations/readme-sync.json'
        record = json.loads(record_path.read_text()) if record_path.exists() else {}
        for name in ('README.md', 'README.en.md'):
            if record.get(name) != digest((root / name).read_text()):
                errors.append('repository README pair needs review: ' + name)
    return errors


def coverage(root: Path = ROOT) -> dict:
    manifest = read_manifest()
    report = {"total": 0, "current": [], "missing": [], "stale": [], "invalid": {}, "readme_errors": readme_errors(root)}
    sources = source_pages(root)
    ignored = ignored_targets(root, [source.relative_to(root / 'docs').as_posix() for source in sources])
    for source in sources:
        name = source.relative_to(root / "docs").as_posix()
        target = root / "translations/en" / name
        report["total"] += 1
        if not target.exists():
            report["missing"].append(name)
            continue
        if name in ignored:
            report['invalid'][name] = ['English source is ignored by Git and would be absent from deployment']
            continue
        entry = manifest.get("pages", {}).get(name, {})
        if entry.get("source_sha256") != digest(source.read_text()) or entry.get("english_sha256") != digest(target.read_text()):
            report["stale"].append(name)
            continue
        errors = structural_errors(source.read_text(), target.read_text())
        if errors:
            report["invalid"][name] = errors
        else:
            report["current"].append(name)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = coverage()
    print(json.dumps(report if args.json else {k: len(v) if isinstance(v, (list, dict)) else v for k, v in report.items()}, ensure_ascii=False, indent=2))
    if not args.report_only and (report["missing"] or report["stale"] or report["invalid"] or report['readme_errors']):
        raise SystemExit(1)
