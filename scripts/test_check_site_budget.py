from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from check_site_budget import check_budget


class BudgetTests(unittest.TestCase):
    def test_per_language_assets_not_summed_twice(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for prefix in ('', 'en'):
                site = root / prefix
                (site / 'javascripts').mkdir(parents=True)
                (site / 'stylesheets').mkdir()
                (site / 'javascripts/app.js').write_text('x' * 80)
                (site / 'stylesheets/app.css').write_text('x' * 30)
                (site / 'index.html').write_text('<html></html>')
            report, errors = check_budget(root, {'custom_javascript_bytes': 100, 'custom_stylesheet_bytes': 40, 'single_html_bytes': 100})
            self.assertEqual(errors, [])
            self.assertTrue(any('en/javascripts' in line for line in report))

    def test_large_assets_and_pages_fail(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'javascripts').mkdir()
            (root / 'javascripts/app.js').write_text('x' * 200)
            (root / 'index.html').write_text('x' * 200)
            _, errors = check_budget(root, {'custom_javascript_bytes': 100, 'custom_stylesheet_bytes': 100, 'single_html_bytes': 100})
            self.assertEqual(len(errors), 2)

    def test_missing_pages_and_invalid_limits_fail(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, errors = check_budget(root, {'custom_javascript_bytes': 100, 'custom_stylesheet_bytes': 100, 'single_html_bytes': 100})
            self.assertIn('No built HTML found', errors)
            with self.assertRaises(ValueError):
                check_budget(root, {'custom_javascript_bytes': -1})


if __name__ == '__main__':
    unittest.main()
