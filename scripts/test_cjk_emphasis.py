from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cjk_emphasis import normalize_cjk_emphasis


class CjkEmphasisTests(unittest.TestCase):
    def test_chinese_and_japanese_punctuation_at_both_boundaries(self):
        self.assertEqual(
            normalize_cjk_emphasis('中文**（重点）**后文。\n- **基础服务不是高可用。**应用\n'),
            '中文<!-- -->**（重点）**<!-- -->后文。\n- **基础服务不是高可用。**<!-- -->应用\n',
        )
        self.assertEqual(normalize_cjk_emphasis('**重要。**API'), '**重要。**<!-- -->API')
        self.assertEqual(normalize_cjk_emphasis('日本語**（重要）**です'), '日本語<!-- -->**（重要）**<!-- -->です')

    def test_code_escaped_stars_and_existing_english_unchanged(self):
        text = ('`**不要。**修改`\n\\*\\*不要。\\*\\*修改\n'
                '普通 **English.** words\na**x.**b\n'
                '```text\n**不要。**修改\n```\n'
                '> ```text\n> **不要。**修改\n> ```\n'
                '    **不要。**修改\n'
                '<pre>\n**不要。**修改\n</pre>\n'
                '<!--\n**不要。**修改\n-->\n'
                '[label](https://example.test/**不要。**修改)\n')
        self.assertEqual(normalize_cjk_emphasis(text), text)

    def test_preserves_inline_code_and_applies_inside_lists_and_tables(self):
        text = '- **内含 `Ready`。**继续\n| **结果：**内容 |\n'
        expected = '- **内含 `Ready`。**<!-- -->继续\n| **结果：**<!-- -->内容 |\n'
        self.assertEqual(normalize_cjk_emphasis(text), expected)
        self.assertEqual(normalize_cjk_emphasis(expected), expected)

    @unittest.skipUnless(shutil.which('zensical'), 'requires Zensical for renderer integration')
    def test_actual_zensical_rendering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'docs').mkdir()
            (root / 'zensical.toml').write_text('[project]\nsite_name = "Test"\ndocs_dir = "docs"\nsite_dir = "site"\n')
            markdown = ('- **基础服务不是高可用。**应用、数据库。\n'
                        '- 中文**（重点）**正文\n'
                        '- **内含 `Ready`。**后文\n'
                        '- `**不要。**修改`\n'
                        '- \\*\\*不要。\\*\\*修改\n\n'
                        '```text\n**不要。**修改\n```\n')
            (root / 'docs/index.md').write_text(normalize_cjk_emphasis(markdown))
            subprocess.run(['zensical', 'build', '--config-file', str(root / 'zensical.toml'), '--clean'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            html = (root / 'site/index.html').read_text()
            self.assertIn('<strong>基础服务不是高可用。</strong><!-- -->应用', html)
            self.assertIn('中文<!-- --><strong>（重点）</strong><!-- -->正文', html)
            self.assertIn('<strong>内含 <code>Ready</code>。</strong><!-- -->后文', html)
            self.assertIn('<code>**不要。**修改</code>', html)
            self.assertRegex(html, r'<li>\*\*不要。\*\*修改</li>')
            self.assertRegex(html, r'(?s)<code[^>]*>.*?\*\*不要。\*\*修改.*?</code>')


if __name__ == '__main__':
    unittest.main()
