"""Translate editable visual labels without changing geometry, data, or executable code."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import html
import json
from pathlib import Path
import re

from bilingual import ROOT, HAN, digest

ASSET_MAP = ROOT / "translations/asset-strings.en.json"
LAYOUT_MAP = ROOT / "translations/visual-layouts.en.json"


def parse_json_response(text):
    fenced = re.fullmatch(r'\s*```(?:json)?\s*\n(.*?)\n```\s*', text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


def unchanged_numbers(source, target):
    def numeric(text):
        scales = {'万': 10000, '亿': 100000000, 'thousand': 1000, 'million': 1000000,
                  'billion': 1000000000, 'k': 1000, 'K': 1000, 'M': 1000000, 'B': 1000000000}
        pattern = r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(万|亿|thousand\b|million\b|billion\b|[kKMB]\b))?'
        return Counter(Decimal(number.replace(',', '')) * scales.get(unit, 1) for number, unit in re.findall(pattern, text))
    original, translated = numeric(source), numeric(target)
    # Chinese prose may spell out small counts, such as 两台八卡 -> two 8-GPU nodes.
    chinese = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    available = Counter(Decimal(chinese[word]) for word in source if word in chinese)
    words = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
    spelled = Counter(Decimal(words[word.lower()]) for word in re.findall(r'\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten)\b', target, re.I))
    return not ((translated - original) - available) and not ((original - translated) - spelled)


def text_nodes(source: str):
    excluded = [match.span() for match in re.finditer(r'<(script|style|code|pre)\b[^>]*>.*?</\1>', source, re.S | re.I)]
    return list(dict.fromkeys(match.group() for match in re.finditer(r'(?<=>)[^<>]+(?=<)', source) if HAN.search(match.group()) and not any(start <= match.start() < end for start, end in excluded)))


def assets():
    return sorted(path for path in (ROOT / "docs").rglob("*") if path.suffix in (".svg", ".html") and text_nodes(path.read_text()))


def asset_errors():
    records = json.loads(ASSET_MAP.read_text()) if ASSET_MAP.exists() else {}
    errors = []
    for path in assets():
        name = path.relative_to(ROOT / "docs").as_posix()
        record = records.get(name, {})
        if record.get("source_sha256") != digest(path.read_text()) or set(record.get("strings", {})) != set(text_nodes(path.read_text())):
            errors.append(name)
        elif any(not isinstance(value, str) or not value or HAN.search(value) or not unchanged_numbers(html.unescape(raw), value) for raw, value in record['strings'].items()):
            errors.append(name + ' (invalid English labels)')
        elif path.suffix == '.svg':
            try:
                localize_asset(path, record)
            except ValueError:
                errors.append(name + ' (English typography missing or stale)')
    return errors


def localize_asset(path: Path, record: dict, use_layout=True):
    source = path.read_text()
    if record["source_sha256"] != digest(source):
        raise ValueError(f"stale asset translation: {path}")
    if path.suffix == '.svg' and use_layout:
        name = path.relative_to(ROOT / 'docs').as_posix()
        layouts = json.loads(LAYOUT_MAP.read_text()) if LAYOUT_MAP.exists() else {}
        layout = layouts.get(name, {})
        target = ROOT / 'translations/en-assets' / name
        label_hash = digest(json.dumps(record['strings'], ensure_ascii=False, sort_keys=True))
        if layout.get('source_sha256') != digest(source) or layout.get('label_sha256') != label_hash or not target.exists() or layout.get('english_sha256') != digest(target.read_text()):
            raise ValueError(f'missing or stale English SVG typography: {name}')
        return target.read_text()
    for raw, english in sorted(record["strings"].items(), key=lambda item: len(item[0]), reverse=True):
        # Replace text content only; never rewrite SVG paths, numeric data, or scripts.
        source = source.replace('>' + raw + '<', '>' + html.escape(english, quote=False) + '<')
    if path.suffix == '.html':
        source = re.sub(r'(<html\b[^>]*\blang=")[^"]+', r'\1en', source)
        # Chinese needs no word separator around inline markup; English does.
        source = re.sub(r'(</(?:strong|em|b|i|a|code)>)(?=[A-Za-z0-9])', r'\1 ', source)
        source = re.sub(r'(?<=[A-Za-z0-9,;:])(<(?:strong|em|b|i|a|code)\b)', r' \1', source)
    return source


def translate_asset(translator, path, records):
    name = path.relative_to(ROOT / "docs").as_posix()
    original = path.read_text()
    if records.get(name, {}).get('source_sha256') == digest(original):
        return
    nodes = text_nodes(original)
    mapping = {}
    for start in range(0, len(nodes), 25):
        batch = nodes[start:start + 25]
        rows = [{"id": f"label{start+i:04d}", "text": html.unescape(text).strip()} for i, text in enumerate(batch)]
        translated = parse_json_response(translator.translate_chunk(json.dumps(rows, ensure_ascii=False, indent=2), name, start // 25))
        if [row['id'] for row in translated] != [row['id'] for row in rows]:
            raise ValueError(f"visual label IDs changed: {name}")
        for raw, row, target in zip(batch, rows, translated):
            english = target['text']
            if HAN.search(english):
                raise ValueError(f"untranslated visual label: {name}")
            if not unchanged_numbers(row['text'], english):
                raise ValueError(f"visual label numbers changed: {name}: {row['id']}")
            mapping[raw] = english
    records[name] = {'source_sha256': digest(original), 'strings': mapping}
    temporary = ASSET_MAP.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(ASSET_MAP)
    print(json.dumps({'event': 'asset', 'asset': name, 'labels': len(mapping)}, ensure_ascii=False), flush=True)


def run(translator):
    records = json.loads(ASSET_MAP.read_text()) if ASSET_MAP.exists() else {}
    failures = []
    for path in assets():
        try:
            translate_asset(translator, path, records)
        except Exception as error:
            failure = {'asset': path.relative_to(ROOT / 'docs').as_posix(), 'error': str(error) if isinstance(error, ValueError) else type(error).__name__}
            failures.append(failure)
            print(json.dumps({'event': 'asset_failed', **failure}, ensure_ascii=False), flush=True)
    (translator.work / 'assets-last-run.json').write_text(json.dumps({'completed': len(records), 'failures': failures}, ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError(f'{len(failures)} visual translations need review; independent assets completed')
