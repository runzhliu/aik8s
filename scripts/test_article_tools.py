from datetime import datetime, timezone
import html
import re
import unittest
from urllib.parse import parse_qs, urlsplit

from article_tools import estimate_reading_minutes, inject_article_tools


class ArticleToolsTests(unittest.TestCase):
    def inject(self, source, **kwargs):
        return inject_article_tools(source, title='GPU <guide>', url='https://aik8s.run/ai-k8s/guide/',
                                    source_path='ai-k8s/guide.md', **kwargs)

    def test_reading_estimate_counts_both_languages_and_code(self):
        english = '<article><h1>Title</h1><p>' + 'word ' * 440 + '</p></article>'
        chinese = '<article><h1>标题</h1><p>' + '字' * 700 + '</p></article>'
        self.assertGreaterEqual(estimate_reading_minutes(english), 2)
        self.assertGreaterEqual(estimate_reading_minutes(chinese), 2)
        code = '<article><pre><code>' + 'x = 1\n' * 160 + '</code></pre></article>'
        self.assertEqual(estimate_reading_minutes(code), 2)

    def test_estimate_ignores_ui_scripts_and_previous_metadata(self):
        source = '<article><h1>Short</h1><p>Small text.</p><nav>' + 'word ' * 1000 + '</nav><script>' + 'word ' * 1000 + '</script><aside>' + 'word ' * 1000 + '</aside></article>'
        self.assertEqual(estimate_reading_minutes(source), 1)
        output = self.inject(source)
        self.assertEqual(estimate_reading_minutes(output), 1)

    def test_feedback_is_prefilled_not_submitted_and_source_is_language_specific(self):
        for language, directory, label in [('zh', 'docs', '反馈问题'), ('en', 'translations/en', 'Report an issue')]:
            with self.subTest(language=language):
                result = self.inject('<article><h1>Title</h1><p>Body</p></article>', language=language)
                self.assertIn(label, result)
                self.assertIn('/blob/main/' + directory + '/ai-k8s/guide.md', result)
                url = html.unescape(re.search(r'href="([^"]+)"[^>]*data-aik8s-feedback', result)[1])
                query = parse_qs(urlsplit(url).query)
                self.assertIn('GPU <guide>', query['title'][0])
                self.assertIn('https://aik8s.run/ai-k8s/guide/', query['body'][0])
                self.assertNotIn('<form', result)
                self.assertIn('rel="noopener"', result)

    def test_only_explicit_review_and_environment_are_shown(self):
        shell = '<article><h1>Title</h1><p>Body</p></article>'
        plain = self.inject(shell)
        self.assertNotIn('内容审阅', plain)
        self.assertNotIn('适用版本', plain)
        self.assertNotIn('实测环境', plain)
        explicit = self.inject(shell, reviewed='2026-10-10', versions='Kubernetes 1.35 <test>', environment='4 × H20')
        self.assertIn('2026-10-10', explicit)
        self.assertIn('Kubernetes 1.35 &lt;test&gt;', explicit)
        self.assertIn('4 × H20', explicit)
        self.assertIn('不等于 Git 更新时间或实测认证', explicit)
        self.assertNotIn('内容审阅', self.inject(shell, reviewed='not-a-date'))

    def test_no_duplicate_ui_or_authored_headings(self):
        shell = '<article><h1>Title</h1><p>Text</p><h2>Section</h2></article>'
        once = self.inject(shell)
        twice = self.inject(once)
        self.assertEqual(twice.count('class="aik8s-article-info"'), 1)
        self.assertEqual(twice.count('<h2'), 1)
        self.assertIn('预计阅读约', twice)
        self.assertEqual(self.inject('<main>No article</main>'), '<main>No article</main>')

    def test_ui_follows_dates_and_refuses_unsafe_source_path(self):
        source = '<article><h1>Title</h1><!-- AIK8S article dates --><p>dates</p><!-- /AIK8S article dates --><p>Content</p></article>'
        output = self.inject(source)
        self.assertLess(output.index('/AIK8S article dates'), output.index('AIK8S article tools'))
        unsafe = inject_article_tools(source, title='Title', url='https://aik8s.run/article/', source_path='../secret.md')
        self.assertNotIn('/blob/main/', unsafe)


if __name__ == '__main__':
    unittest.main()
