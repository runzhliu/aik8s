"""Keep case-study navigation integrated without changing existing article routes."""
import json
from pathlib import Path
import tomllib
import unittest

from build_bilingual import translate_navigation

ROOT = Path(__file__).resolve().parent.parent


def locations(value, parents=()):
    if isinstance(value, str):
        yield value, parents
    elif isinstance(value, list):
        for child in value:
            yield from locations(child, parents)
    else:
        for label, child in value.items():
            yield from locations(child, (*parents, label))


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.navigation = tomllib.loads((ROOT / 'zensical.toml').read_text())['project']['nav']
        cls.labels = json.loads((ROOT / 'translations/navigation.en.json').read_text())

    def test_single_technical_root_and_cases_distributed_by_subject(self):
        roots = [label for entry in self.navigation for label in entry]
        self.assertEqual(roots, ['首页', 'AI/LLM on Kubernetes'])
        moved = {
            'cases/index.md': '实战、排障与选型',
            'cases/ai-cluster-component-checklist.md': '参考架构与实验',
            'k3s-upgrade/index.md': '平台工程与生产运维',
            'k3s-upgrade/report.md': '平台工程与生产运维',
        }
        routes = list(locations(self.navigation))
        for path, section in moved.items():
            with self.subTest(path=path):
                matches = [parents for target, parents in routes if target == path]
                self.assertEqual(len(matches), 1, 'Each moved page has exactly one navigation entry')
                self.assertEqual(matches[0][:2], ('AI/LLM on Kubernetes', section))
                self.assertTrue((ROOT / 'docs' / path).is_file(), 'Original Chinese route remains')
                self.assertTrue((ROOT / 'translations/en' / path).is_file(), 'Original English route remains')

    def test_english_navigation_has_the_same_routes_and_structure(self):
        english = translate_navigation(self.navigation, self.labels)
        self.assertEqual([label for entry in english for label in entry], ['Home', 'AI/LLM on Kubernetes'])
        chinese_routes = list(locations(self.navigation))
        english_routes = list(locations(english))
        self.assertEqual([path for path, _ in chinese_routes], [path for path, _ in english_routes])
        for (_, source), (_, translated) in zip(chinese_routes, english_routes):
            self.assertEqual(tuple(self.labels[label] for label in source), translated)
        self.assertIn(('cases/index.md', ('AI/LLM on Kubernetes', 'Practice, Troubleshooting, and Selection', 'Engineering Case Studies')), english_routes)


if __name__ == '__main__':
    unittest.main()
