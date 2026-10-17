"""Static, bilingual reading estimates and explicit article provenance.

Reading estimates exclude experiments, weight prose/code separately, and are not
verification claims. Review dates and environment/version strings are displayed
only when explicitly authored; a Git timestamp is never substituted for review.
"""
from __future__ import annotations

from datetime import date
import html
from html.parser import HTMLParser
import math
import re
from urllib.parse import quote, urlencode

MARKER = re.compile(r'\n?<!-- AIK8S article tools -->.*?<!-- /AIK8S article tools -->\n?', re.S)
REPO = 'https://github.com/runzhliu/aik8s'


class ReadingText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.stack = []
        self.text = []
        self.code = []
        self.images = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'article':
            self.depth += 1
        if not self.depth:
            return
        values = dict(attrs)
        ignored = tag in {'script', 'style', 'nav', 'aside'} or any(
            name.startswith(('aik8s-article-', 'aik8s-related', 'aik8s-share', 'aik8s-comments'))
            for name in (values.get('class') or '').split()
        )
        self.stack.append((tag, ignored)) if tag not in {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr'} else None
        if tag == 'img' and not any(skip for _, skip in self.stack):
            self.images += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr'}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag == 'article':
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and not any(skip for _, skip in self.stack):
            if any(tag == 'pre' for tag, _ in self.stack):
                self.code.append(data)
            else:
                self.text.append(data)


def estimate_reading_minutes(source: str) -> int:
    parser = ReadingText()
    parser.feed(source)
    text = ' '.join(parser.text)
    cjk = len(re.findall(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))
    words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text))
    code_lines = sum(bool(line.strip()) for line in ''.join(parser.code).splitlines())
    return max(1, math.ceil(cjk / 350 + words / 220 + code_lines / 80 + parser.images / 6))


def inject_article_tools(source: str, *, title: str, url: str, source_path: str,
                         language: str = 'zh', reviewed: str = '', versions: str = '', environment: str = '') -> str:
    source = MARKER.sub('\n', source)
    heading = re.search(r'<article\b[^>]*>.*?</h1\s*>', source, re.S | re.I)
    if not heading:
        return source
    english = language == 'en'
    minutes = estimate_reading_minutes(source)
    estimate = f'About {minutes} min read' if english else f'预计阅读约 {minutes} 分钟'
    note = 'Estimate excludes hands-on experiments.' if english else '阅读时间为估算，不包含动手实验。'
    details = ['<span title="' + note + '">' + estimate + '</span>']
    if reviewed:
        try:
            reviewed = date.fromisoformat(reviewed).isoformat()
        except ValueError:
            reviewed = ''
        if reviewed:
            label = 'Content reviewed' if english else '内容审阅'
            explanation = 'Authored last_reviewed metadata, not the Git update date or a test certification.' if english else '来自人工维护的 last_reviewed，不等于 Git 更新时间或实测认证。'
            details.append('<span title="' + explanation + '">' + label + ' <time datetime="' + reviewed + '">' + reviewed + '</time></span>')
    for label, value in [(('Applicable versions' if english else '适用版本'), versions),
                         (('Test environment' if english else '实测环境'), environment)]:
        if value.strip():
            details.append('<span>' + label + (': ' if english else '：') + html.escape(value) + '</span>')
    issue_title = ('Content feedback: ' if english else '内容反馈：') + title
    body = (f'Article / 文章：{url}\n\n'
            + ('Problem or correction:\n\nEnvironment / version (optional):\n' if english else '问题描述或修正建议：\n\n环境与版本（可选）：\n'))
    issue = REPO + '/issues/new?' + urlencode({'title': issue_title, 'body': body})
    feedback_label = 'Report an issue' if english else '反馈问题'
    feedback_note = 'Opens GitHub; sign-in may be required. Review the issue before submitting.' if english else '前往 GitHub，可能需要登录；确认内容后再提交。'
    links = ['<a href="' + html.escape(issue, quote=True) + '" target="_blank" rel="noopener" title="' + feedback_note + '" data-aik8s-feedback>' + feedback_label + '</a>']
    if source_path and '..' not in source_path.split('/') and not source_path.startswith('/'):
        directory = 'translations/en/' if english else 'docs/'
        source_url = REPO + '/blob/main/' + directory + quote(source_path, safe='/')
        links.append('<a href="' + html.escape(source_url, quote=True) + '" target="_blank" rel="noopener">' + ('View source' if english else '查看源码') + '</a>')
    block = ('\n<!-- AIK8S article tools -->\n<div class="aik8s-article-info" role="group" aria-label="'
             + ('Reading information and feedback' if english else '阅读信息与反馈') + '"><div class="aik8s-article-info__details">'
             + ''.join(details) + '</div><nav aria-label="' + ('Article tools' if english else '文章工具') + '">' + ' '.join(links)
             + '</nav></div>\n<!-- /AIK8S article tools -->\n')
    dates = re.search(r'<!-- AIK8S article dates -->.*?<!-- /AIK8S article dates -->', source, re.S)
    position = dates.end() if dates else heading.end()
    return source[:position] + block + source[position:]
