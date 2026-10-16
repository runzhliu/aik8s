"""Keep quoted experiment inputs available beside their English readings."""
import json
import re

from bilingual import ROOT, digest

PROMPTS = ROOT / 'translations/prompt-originals.json'
QUOTES = re.compile(r'(?m)(?:^>[^\n]*(?:\n|$))+')


def prompt_errors():
    errors = []
    for name, records in json.loads(PROMPTS.read_text()).items():
        for folder, key in [('docs', 'source_sha256'), ('translations/en', 'english_sha256')]:
            path = ROOT / folder / name
            quotes = QUOTES.findall(path.read_text()) if path.exists() else []
            for record in records:
                index = record['quote_index']
                if index >= len(quotes) or digest(quotes[index]) != record[key]:
                    errors.append(f'{name}: quoted prompt {index + 1} needs paired review ({folder})')
    return errors


def preserve_prompt_originals(name, english):
    records = json.loads(PROMPTS.read_text()).get(name, [])
    if not records:
        return english
    source = QUOTES.findall((ROOT / 'docs' / name).read_text())
    matches = list(QUOTES.finditer(english))
    for record in reversed(records):
        index = record['quote_index']
        match = matches[index]
        replacement = ('**English reading of the prompt** — use the original input below when reproducing the example.\n\n'
                       + match.group() + '\n<details markdown>\n<summary>Original prompt (verbatim)</summary>\n\n'
                       + source[index] + '\n</details>\n')
        english = english[:match.start()] + replacement + english[match.end():]
    return english
