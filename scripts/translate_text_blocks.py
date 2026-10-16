"""English readings of Chinese plaintext diagrams, formulas, and captured examples.

The original block is always retained verbatim; translations are reader aids,
not replacements for executable fixtures or the original benchmark prompts.
"""
from __future__ import annotations

import json
import re

from bilingual import ROOT, HAN, digest, protect, source_pages
from translate_assets import parse_json_response, unchanged_numbers

BLOCK_MAP = ROOT / 'translations/text-blocks.en.json'
PLAIN = re.compile(r'^(`{3,}|~{3,})(?:text|plaintext)?[ \t]*\n(.*)\n\1$', re.S)


def plaintext_blocks(text):
    _, literals = protect(text)
    return list(dict.fromkeys(block for block in literals.values() if PLAIN.fullmatch(block) and HAN.search(block)))


def required_blocks():
    records = {}
    for page in source_pages():
        for block in plaintext_blocks(page.read_text()):
            key = digest(block)
            records.setdefault(key, {'original': block, 'pages': []})['pages'].append(page.relative_to(ROOT / 'docs').as_posix())
    return records


def block_errors():
    records = json.loads(BLOCK_MAP.read_text()) if BLOCK_MAP.exists() else {}
    errors = []
    for key, source in required_blocks().items():
        english = records.get(key, {}).get('translation', '')
        original = PLAIN.fullmatch(source['original']).group(2)
        if not english or HAN.search(english) or len(english) < len(original)*.5 or not unchanged_numbers(original, english):
            errors.append(key)
    return errors


def english_readings(text):
    records = json.loads(BLOCK_MAP.read_text()) if BLOCK_MAP.exists() else {}
    for block in plaintext_blocks(text):
        record = records.get(digest(block))
        if record:
            # Eight backticks avoid prematurely closing the English reading if
            # the captured text itself contains shorter Markdown fences.
            replacement = ('<div class="aik8s-translation-reading" markdown>\n\n'
                           '**English rendering** — the original text is retained below.\n\n'
                           '````````text\n' + record['translation'].strip() + '\n````````\n\n'
                           '<details markdown>\n<summary>Original text (verbatim)</summary>\n\n' + block +
                           '\n\n</details>\n</div>')
            text = text.replace(block, replacement)
    return text


def run(translator):
    records = json.loads(BLOCK_MAP.read_text()) if BLOCK_MAP.exists() else {}
    required = required_blocks()
    invalid = set(block_errors())
    pending = [(key, value) for key, value in required.items() if key not in records or key in invalid]
    batches, batch, length = [], [], 0
    for item in pending:
        size = len(item[1]['original'])
        if batch and (length + size > 4000 or len(batch) >= 8):
            batches.append(batch)
            batch, length = [], 0
        batch.append(item)
        length += size
    if batch:
        batches.append(batch)
    failures = []
    for number, batch in enumerate(batches):
        try:
            rows = [{'id': f'block{index:04d}', 'text': PLAIN.fullmatch(value['original']).group(2)} for index, (key, value) in enumerate(batch)]
            translated = parse_json_response(translator.translate_chunk(json.dumps(rows, ensure_ascii=False, indent=2), 'plaintext-readings', number))
            if [row['id'] for row in translated] != [row['id'] for row in rows]:
                raise ValueError('plaintext IDs changed')
            # One bad reading must not discard independent valid entries from
            # the same response. Invalid entries stay pending on the next run.
            for (key, original), source, target in zip(batch, rows, translated):
                english = target.get('text', '')
                if not isinstance(english, str) or not english or HAN.search(english) or len(english) < len(source['text'])*.5 or not unchanged_numbers(source['text'], english):
                    failure = {'batch': number, 'blocks': [key], 'error': 'English reading failed completeness or numeric checks'}
                    failures.append(failure)
                    print(json.dumps({'event': 'plaintext_failed', **failure}), flush=True)
                    continue
                records[key] = {'translation': english, 'pages': original['pages']}
            temporary = BLOCK_MAP.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
            temporary.replace(BLOCK_MAP)
            print(json.dumps({'event': 'plaintext', 'completed': len(records), 'total': len(required), 'batch': number}), flush=True)
        except Exception as error:
            failure = {'batch': number, 'blocks': [key for key, _ in batch], 'error': str(error) if isinstance(error, ValueError) else type(error).__name__}
            failures.append(failure)
            print(json.dumps({'event': 'plaintext_failed', **failure}), flush=True)
    (translator.work / 'plaintext-last-run.json').write_text(json.dumps({'completed': len(records), 'total': len(required), 'failures': failures}, ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError(f'{len(failures)} plaintext batches need review; independent batches completed')
