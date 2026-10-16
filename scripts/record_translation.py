#!/usr/bin/env python3
"""Record a reviewed Chinese/English pair after deterministic integrity checks."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from bilingual import ROOT, MANIFEST, digest, read_manifest, structural_errors, readme_errors

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("page", nargs='?', help="path relative to docs/, for example ai-k8s/cluster/architecture.md")
parser.add_argument('--readme', action='store_true', help='record the reviewed repository README language pair')
args = parser.parse_args()
if args.readme:
    if args.page:
        parser.error('choose a document page or --readme')
    errors = readme_errors(ROOT, check_sync=False)
    if errors:
        parser.error('; '.join(errors))
    record = {name: digest((ROOT / name).read_text()) for name in ('README.md', 'README.en.md')}
    record['reviewed_at'] = datetime.now(timezone.utc).isoformat()
    (ROOT / 'translations/readme-sync.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Recorded reviewed repository README pair')
    raise SystemExit(0)
if not args.page:
    parser.error('provide a document page or --readme')
relative = Path(args.page)
if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".md":
    parser.error("page must be a relative Markdown path inside docs/")
source = (ROOT / "docs" / relative).read_text()
english = (ROOT / "translations/en" / relative).read_text()
errors = structural_errors(source, english)
if errors:
    parser.error("; ".join(errors))
manifest = read_manifest()
entry = manifest["pages"].setdefault(relative.as_posix(), {})
entry.update(source_sha256=digest(source), english_sha256=digest(english), reviewed_at=datetime.now(timezone.utc).isoformat(), review="reviewed against source")
temporary = MANIFEST.with_suffix(".json.tmp")
temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
temporary.replace(MANIFEST)
print("Recorded reviewed translation:", relative)
