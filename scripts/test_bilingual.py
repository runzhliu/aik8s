import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import xml.etree.ElementTree as ET

from bilingual import protect, restore, structural_errors, ignored_targets, readme_errors
from translate_docs import chunks, remove_added_inline_formatting
from build_bilingual import bind_linked_heading_ids, combine_sitemaps, heading_aliases, localize_document_links, rendered_path, translate_navigation, SITEMAP, XHTML
from translate_assets import parse_json_response, text_nodes, unchanged_numbers, localize_asset
import translate_text_blocks
import preserve_prompt_originals
from bilingual import digest


class BilingualIntegrityTests(unittest.TestCase):
    def test_original_prompt_is_visible_without_replacing_the_english_reading(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'docs').mkdir()
            (root / 'translations/en').mkdir(parents=True)
            source = '# 例子\n\n> 保持原始测试输入。\n\n'
            target = '# Example\n\n> Keep the original test input.\n\n'
            (root / 'docs/example.md').write_text(source)
            (root / 'translations/en/example.md').write_text(target)
            records = {'example.md': [{'quote_index': 0, 'source_sha256': digest('> 保持原始测试输入。\n'), 'english_sha256': digest('> Keep the original test input.\n')}]}
            mapping = root / 'translations/prompt-originals.json'
            mapping.write_text(json.dumps(records))
            with patch.object(preserve_prompt_originals, 'ROOT', root), patch.object(preserve_prompt_originals, 'PROMPTS', mapping):
                self.assertEqual(preserve_prompt_originals.prompt_errors(), [])
                result = preserve_prompt_originals.preserve_prompt_originals('example.md', target)
                self.assertIn('> Keep the original test input.', result)
                self.assertIn('> 保持原始测试输入。', result)
                (root / 'docs/example.md').write_text(source.replace('原始', '修改后的'))
                self.assertTrue(preserve_prompt_originals.prompt_errors())

    def test_repository_readmes_have_reciprocal_links_and_fresh_review_record(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'translations').mkdir()
            links = '[简体中文](README.md) | [English](README.en.md)'
            for name in ('README.md', 'README.en.md'):
                (root / name).write_text(links)
            record = {name: digest(links) for name in ('README.md', 'README.en.md')}
            (root / 'translations/readme-sync.json').write_text(json.dumps(record))
            self.assertEqual(readme_errors(root), [])
            (root / 'README.md').write_text(links + '\nNew content')
            self.assertTrue(readme_errors(root))

    def test_ignored_english_sources_are_not_counted_as_publishable(self):
        import subprocess
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.gitignore').write_text('**/*test-plan.md\n!/translations/en/published-test-plan.md\n')
            self.assertEqual(ignored_targets(root, ['published-test-plan.md', 'private-test-plan.md', 'article.md']), {'private-test-plan.md'})

    def test_executable_fixture_and_links_survive_round_trip(self):
        source = '# 标题\n\n[说明](../a.md#配置)\n\n```sh\nprintf "中文 prompt"\n```\n\n使用 `model-v1`，参见 https://example.org/a。\n'
        protected, saved = protect(source)
        self.assertNotIn('printf', protected)
        self.assertNotIn('../a.md', protected)
        self.assertEqual(restore(protected, saved), source)

    def test_missing_literal_is_an_error(self):
        text, saved = protect('执行 `kubectl get pods`。')
        with self.assertRaises(ValueError):
            restore('Run the command.', saved)

    def test_changed_code_and_truncated_sections_are_rejected(self):
        source = '# 中文\n\n## 方法\n\n```sh\necho 1\n```\n'
        self.assertEqual(structural_errors(source, '# English\n\n## Method\n\n```sh\necho 1\n```\n'), [])
        self.assertIn('code, URLs, link destinations or explicit anchors changed', structural_errors(source, '# English\n\n## Method\n\n```sh\necho 2\n```\n'))
        self.assertIn('heading levels/count changed', structural_errors(source, '# English\n'))

    def test_frontmatter_cannot_disappear_lose_its_end_marker_or_change_review_dates(self):
        source = '---\ntitle: 标题\nstatus: reviewed\nlast_reviewed: 2026-09-20\n---\n\n# 标题\n'
        target = '---\ntitle: "English: Title"\nstatus: reviewed\nlast_reviewed: 2026-09-20\n---\n\n# English\n'
        self.assertEqual(structural_errors(source, target), [])
        self.assertIn('front matter missing, malformed, or field names changed', structural_errors(source, '# English\n'))
        self.assertIn('front matter missing, malformed, or field names changed', structural_errors(source, target.replace('\n---\n', '\n', 1)))
        self.assertIn('non-prose front matter changed: last_reviewed', structural_errors(source, target.replace('2026-09-20', '2026-09-21')))

    def test_chunking_keeps_original_whitespace(self):
        text = '# 第一部分\n\n内容\n\n## 第二部分\n\n后续\n'
        self.assertEqual(''.join(chunks(text, 12)), text)

    def test_categories_translate_but_cannot_drop_items(self):
        source = '---\ncategories:\n  - 推理\n  - 实战\n---\n\n# 标题\n'
        target = '---\ncategories:\n  - Inference\n  - Hands-on\n---\n\n# Title\n'
        self.assertEqual(structural_errors(source, target), [])
        self.assertIn('front matter category list structure changed', structural_errors(source, target.replace('  - Hands-on\n', '')))

    def test_chunking_never_splits_a_mermaid_graph_at_its_blank_lines(self):
        graph = '```mermaid\nflowchart LR\n A[应用] --> B[服务]\n\n B --> C[结果]\n```\n'
        text = 'Intro\n\n' + graph + '\nConclusion\n'
        parts = chunks(text, 30)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(any(graph in part for part in parts))

    def test_adding_a_table_cell_is_rejected_even_when_row_count_matches(self):
        source = '| 指标 | 结果 |\n| --- | --- |\n| 吞吐 | 125 |\n'
        target = '| Metric | Result |\n| --- | --- |\n| Throughput | 125 | extra |\n'
        self.assertIn('Markdown table column structure changed', structural_errors(source, target))

    def test_ui_labels_can_translate_but_calculator_input_names_cannot(self):
        source = '<label>参数量<input name="params" value="70" title="参数"></label>'
        target = '<label>Parameters<input name="params" value="70" title="Parameters"></label>'
        self.assertEqual(structural_errors(source, target), [])
        self.assertIn('inline HTML elements or functional attributes changed', structural_errors(source, target.replace('name="params"', 'name="parameters"')))

    def test_mermaid_labels_are_not_frozen(self):
        source = '```mermaid\nflowchart LR\n a[节点] --> b[服务]\n```\n'
        protected, saved = protect(source)
        self.assertIn('节点', protected)
        self.assertEqual(restore(protected, saved), source)

    def test_mermaid_closing_fence_never_hides_following_prose_or_headings(self):
        source = '# 标题\n\n```mermaid\nflowchart LR\n a[节点] --> b[服务]\n```\n\n## 后续步骤\n\n这里必须翻译。\n\n```sh\necho 保留代码\n```\n\n结语也必须翻译。\n'
        protected, saved = protect(source)
        self.assertIn('## 后续步骤', protected)
        self.assertIn('这里必须翻译', protected)
        self.assertIn('结语也必须翻译', protected)
        self.assertNotIn('echo 保留代码', protected)
        self.assertEqual(restore(protected, saved), source)
        self.assertEqual(len(saved), 1)
        self.assertEqual(protect('```sh\necho 1\n```')[1], {'AIK8S_LITERAL_00000_END': '```sh\necho 1\n```'})

    def test_translating_mermaid_labels_cannot_change_its_edges_or_shapes(self):
        source = '```mermaid\nflowchart LR\n A[应用] -->|请求| B{审批}\n B -.确认.-> C[执行]\n```\n'
        target = '```mermaid\nflowchart LR\n A[Application] -->|Request| B{Approval}\n B -.Confirm.-> C[Execute]\n```\n'
        self.assertEqual(structural_errors(source, target), [])
        self.assertIn('Mermaid graph topology or node shapes changed', structural_errors(source, target.replace('B -.Confirm.-> C', 'C -.Confirm.-> B')))

    def test_added_code_formatting_is_removed_without_touching_original_literals_or_mermaid(self):
        original = '# 标题\n\n运行 `kubectl get pods`。\n\n```mermaid\ngraph LR\n a[节点] --> b[服务]\n```\n'
        protected, saved = protect(original)
        translated = protected.replace('标题', 'Title').replace('运行 ', 'Run ').replace('。', '.').replace('节点', 'Node').replace('服务', 'Service')
        translated = translated.replace('Run ', 'Run `extra formatting` then ')
        fixed, count = remove_added_inline_formatting(translated)
        self.assertEqual(count, 1)
        result = restore(fixed, saved)
        self.assertIn('Run extra formatting then `kubectl get pods`.', result)
        self.assertIn('```mermaid\ngraph LR\n a[Node] --> b[Service]\n```', result)

    def test_navigation_translation_rejects_missing_labels_and_prunes_private_preview(self):
        nav = [{"栏目": ["index.md", {"文章": "a.md"}]}]
        labels = {"栏目": "Section", "文章": "Article"}
        self.assertEqual(translate_navigation(nav, labels), [{"Section": ["index.md", {"Article": "a.md"}]}])
        self.assertEqual(translate_navigation(nav, labels, {"index.md"}), [{"Section": ["index.md"]}])
        with self.assertRaises(ValueError):
            translate_navigation(nav, {})

    def test_heading_aliases_keep_inbound_chinese_fragments_without_duplicate_ids(self):
        zh = '<article><h1 id="title">标题</h1><h2 id="配置">配置</h2></article>'
        en = '<article><h1 id="title">Title</h1><h2 id="configuration">Configuration</h2></article>'
        result = heading_aliases(zh, en)
        self.assertEqual(result.count('id="title"'), 1)
        self.assertIn('id="配置"', result)
        self.assertIn('id="configuration"', result)
        self.assertEqual(heading_aliases(zh, result), result)
        with self.assertRaises(ValueError):
            heading_aliases(zh, '<article><h1 id="title">Title</h1></article>')

    def test_linked_source_ids_are_available_during_strict_build_without_touching_code(self):
        source = '<article><h1 id="title">标题</h1><h2 id="6-kubevirt">资源隔离</h2></article>'
        english = '# Title\n\n```sh\n# example comment\n```\n\n## 6. Resource isolation with KubeVirt\n'
        result = bind_linked_heading_ids(english, source, {'6-kubevirt'})
        self.assertIn('## 6. Resource isolation with KubeVirt { #6-kubevirt }', result)
        self.assertIn('# Title\n', result)
        self.assertIn('```sh\n# example comment\n```', result)
        self.assertEqual(bind_linked_heading_ids(result, source, {'6-kubevirt'}), result)

    def test_explicit_heading_anchor_cannot_move_into_the_middle_of_a_title(self):
        source = '## 原始标题 { #stable }\n'
        self.assertEqual(structural_errors(source, '## Original title { #stable }\n'), [])
        self.assertIn('explicit heading ID must remain at the end of the heading', structural_errors(source, '## Original { #stable } title\n'))

    def test_combined_sitemap_keeps_both_languages_and_reciprocal_alternates(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "en").mkdir()
            for prefix in ("", "en/"):
                (root / prefix / "sitemap.xml").write_text(f'<urlset xmlns="{SITEMAP}"><url><loc>https://aik8s.run/{prefix}a/</loc><lastmod>2026-10-16</lastmod></url></urlset>')
            combine_sitemaps(root)
            urls = ET.parse(root / "sitemap.xml").getroot()
            self.assertEqual(len(urls), 2)
            for url in urls:
                alternatives = {item.attrib['hreflang']: item.attrib['href'] for item in url.findall(f'{{{XHTML}}}link')}
                self.assertEqual(alternatives, {"zh-Hans": "https://aik8s.run/a/", "en": "https://aik8s.run/en/a/", "x-default": "https://aik8s.run/a/"})
            self.assertTrue((root / "sitemap.xml.gz").exists())
            combined = (root / 'sitemap.xml').read_bytes()
            combine_sitemaps(root)
            self.assertEqual((root / 'sitemap.xml').read_bytes(), combined)

    def test_article_and_index_output_paths_match_zensical(self):
        self.assertEqual(rendered_path('index.md'), Path('index.html'))
        self.assertEqual(rendered_path('a/index.md'), Path('a/index.html'))
        self.assertEqual(rendered_path('a/topic.md'), Path('a/topic/index.html'))
        self.assertEqual(rendered_path('assets/proof/README.md'), Path('assets/proof/index.html'))

    def test_english_asset_and_page_links_localize_without_changing_executable_examples(self):
        source = '[Figure](/assets/diagram.svg)\n<img src="/assets/diagram.svg" alt="Diagram">\n[Article](https://aik8s.run/ai-k8s/a/)\n`/assets/literal.svg`\n```sh\ncurl https://aik8s.run/ai-k8s/a/\n```\n'
        result = localize_document_links(source)
        self.assertIn('[Figure](/en/assets/diagram.svg)', result)
        self.assertIn('src="/en/assets/diagram.svg"', result)
        self.assertIn('redirect_to: /en/ai-k8s/a/', localize_document_links('---\nredirect_to: /ai-k8s/a/\n---\n'))
        self.assertIn('[Article](https://aik8s.run/en/ai-k8s/a/)', result)
        self.assertIn('`/assets/literal.svg`', result)
        self.assertIn('curl https://aik8s.run/ai-k8s/a/', result)
        self.assertEqual(localize_document_links('[简体中文](/)\n[English](/en/)', homepage=True), '[简体中文](/)\n[English](/en/)')

    def test_translated_visual_counts_accept_chinese_numerals_but_reject_data_changes(self):
        self.assertTrue(unchanged_numbers('两台八卡 H20，20.0 秒', 'two 8-GPU H20 nodes, 20 seconds'))
        self.assertFalse(unchanged_numbers('两台八卡 H20，20 秒', 'two 9-GPU H20 nodes, 20 seconds'))
        self.assertFalse(unchanged_numbers('P95 3.14 ms', 'P95 3.41 ms'))
        self.assertTrue(unchanged_numbers('5000 万序列、166.7 万样本/秒、1440 亿样本/天', '50 million series, 1.667 million samples/s, 144 billion samples/day'))
        self.assertFalse(unchanged_numbers('5000 万序列', '500 million series'))
        self.assertTrue(unchanged_numbers('35 万+ QPS', '350k+ QPS'))
        self.assertEqual(parse_json_response('```json\n[{"id":"a","text":"English"}]\n```'), [{'id': 'a', 'text': 'English'}])

    def test_visual_label_extraction_leaves_scripts_and_captured_code_untouched(self):
        source = '<style>/* 中文 */</style><h1>结果</h1><pre>原始输出</pre><code>中文 prompt</code><script>let x="中文";</script><p>说明</p>'
        self.assertEqual(text_nodes(source), ['结果', '说明'])

    def test_english_html_keeps_word_spacing_at_inline_markup_boundaries(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'index.html'
            original = '<html lang="zh"><p><strong>更快。</strong>这是测试。</p><p>返回<code>Ready</code>之后继续。</p></html>'
            path.write_text(original)
            result = localize_asset(path, {'source_sha256': digest(original), 'strings': {'更快。': 'Faster.', '这是测试。': 'This is a test.', '返回': 'Returns', '之后继续。': 'Then continue.'}})
            self.assertIn('<strong>Faster.</strong> This is a test.', result)
            self.assertIn('Returns <code>Ready</code> Then continue.', result)

    def test_english_plaintext_reading_keeps_the_original_fixture_verbatim(self):
        block = '```text\n原始提示词：用 4 张 GPU\n结果 200\n```'
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'blocks.json'
            path.write_text(json.dumps({digest(block): {'translation': 'Original prompt: use 4 GPUs\nResult 200'}}))
            with patch.object(translate_text_blocks, 'BLOCK_MAP', path):
                result = translate_text_blocks.english_readings('# Test\n\n'+block+'\n')
            self.assertIn(block, result)
            self.assertIn('Original prompt: use 4 GPUs\nResult 200', result)
            self.assertIn('Original text (verbatim)', result)
            self.assertEqual(result.count('# Test'), 1)


if __name__ == '__main__':
    unittest.main()
