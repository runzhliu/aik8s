#!/usr/bin/env python3
"""Build a public, token-free fallback snapshot of owner-authored moment issues."""
import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
API = 'repos/runzhliu/aik8s/issues'

def pages(path):
    result = subprocess.run(['gh','api','--paginate','--slurp','-H','Accept: application/vnd.github+json',path], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    if not isinstance(data, list) or not all(isinstance(page, list) for page in data):
        raise ValueError('Unexpected GitHub response')
    return [item for page in data for item in page]

def main():
    query = urlencode({'state':'open','labels':'moments','creator':'runzhliu','sort':'created','direction':'desc','per_page':'100'})
    issues = []
    comments = {}
    for issue in pages(f'{API}?{query}'):
        if issue.get('pull_request') or issue.get('user',{}).get('login','').lower() != 'runzhliu':
            continue
        if not any(label.get('name') == 'moments' for label in issue.get('labels',[])):
            continue
        number = issue['number']
        issues.append({k:issue.get(k) for k in ('number','created_at','user','labels','comments','reactions','body')})
        if issue.get('comments'):
            comments[str(number)] = [{'user':{'login':c.get('user',{}).get('login','')},'body':c.get('body','')} for c in pages(f'{API}/{number}/comments?per_page=100')]
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'site/assets/data/moments-issues.json')
    out = parser.parse_args().output
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'issues':issues,'comments':comments},ensure_ascii=False,separators=(',',':'))+'\n')
    print(f'Generated public moments snapshot: {len(issues)} issues')

if __name__ == '__main__':main()
