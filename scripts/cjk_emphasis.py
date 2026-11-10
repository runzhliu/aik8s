"""Normalize CJK-adjacent strong emphasis before CommonMark rendering.

Inline HTML comments give the delimiter an unambiguous punctuation neighbor
without adding characters to the visible or copied text. Source files are not
modified: callers apply this only to generated staging documents.
"""
from __future__ import annotations

import re
import unicodedata

_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_STRONG = re.compile(r"(?<![\\*])\*\*(?!\*)([^*\r\n]+?)(?<!\\)\*\*(?!\*)")
_FENCE = re.compile(r"^\s*(?:>\s*)*(?:(?:[-+*]|\d+[.)])\s+)?\s*(`{3,}|~{3,})")
_RAW_OPEN = re.compile(r"^\s*(?:>\s*)*<(pre|script|style)(?:\s|>)", re.I)


def _punct(char: str) -> bool:
    return bool(char) and unicodedata.category(char).startswith(('P', 'S'))


def _inline_protected(line: str) -> list[tuple[int, int]]:
    """Find inline code, HTML tags/comments and Markdown link destinations."""
    protected = [(m.start(), m.end()) for m in re.finditer(r'<!--.*?-->|<[^>]*>', line)]
    i = 0
    while i < len(line):
        if line[i] == '\\':
            i += 2
            continue
        if line[i] == '`':
            end_run = i + 1
            while end_run < len(line) and line[end_run] == '`':
                end_run += 1
            run = line[i:end_run]
            close = re.search(r'(?<!`)' + re.escape(run) + r'(?!`)', line[end_run:])
            if close:
                end = end_run + close.end()
                protected.append((i, end))
                i = end
                continue
            i = end_run
            continue
        if line.startswith('](', i):
            j, depth = i + 2, 1
            while j < len(line) and depth:
                if line[j] == '\\':
                    j += 2
                    continue
                if line[j] == '(':
                    depth += 1
                elif line[j] == ')':
                    depth -= 1
                j += 1
            protected.append((i + 1, j))
            i = j
            continue
        i += 1
    return protected


def normalize_cjk_emphasis(markdown: str) -> str:
    output: list[str] = []
    fence: str | None = None
    raw: str | None = None
    comment = False
    for line in markdown.splitlines(keepends=True):
        stripped = re.sub(r'^\s*(?:>\s*)*', '', line)
        marker = _FENCE.match(line)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            output.append(line)
            continue
        if marker:
            fence = marker.group(1)
            output.append(line)
            continue
        if raw:
            if re.search(r'</' + raw + r'\s*>', line, re.I):
                raw = None
            output.append(line)
            continue
        opening = _RAW_OPEN.match(line)
        if opening:
            if not re.search(r'</' + opening.group(1) + r'\s*>', line, re.I):
                raw = opening.group(1)
            output.append(line)
            continue
        if comment:
            if '-->' in line:
                comment = False
            output.append(line)
            continue
        if stripped.startswith('<!--') and '-->' not in stripped:
            comment = True
            output.append(line)
            continue
        # Indented code: stay conservative for four-space list continuations too.
        if re.match(r'^(?: {4}|\t)', line):
            output.append(line)
            continue
        protected = _inline_protected(line)
        def inside(position: int) -> bool:
            return any(start <= position < end for start, end in protected)
        def replace(match: re.Match[str]) -> str:
            if inside(match.start()) or inside(match.end() - 1):
                return match.group(0)
            content = match.group(1)
            before = line[match.start() - 1:match.start()] if match.start() else ''
            after = line[match.end():match.end() + 1]
            cjk = bool(_CJK.search(content))
            fix_open = _punct(content[0]) and before.isalnum() and (cjk or bool(_CJK.search(before)))
            fix_close = _punct(content[-1]) and after.isalnum() and (cjk or bool(_CJK.search(after)))
            return ('<!-- -->' if fix_open else '') + match.group(0) + ('<!-- -->' if fix_close else '')
        output.append(_STRONG.sub(replace, line))
    return ''.join(output)
