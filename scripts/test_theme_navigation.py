"""Keep the pinned theme adaptation narrow and upgrade failures explicit."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from theme_navigation import MARKER, adapt_language_navigation, adapt_theme_assets

BUNDLE = ('function wc({document$:e}){let t=new Map;e.pipe(y(()=>$("link[rel=alternate]")),d(r=>new URL(r.href)))}'
          'var gt=Ai();Ec({alert$:No});wc({document$:gt});var Fc=vr(In.base);search();')


class ThemeNavigationTests(unittest.TestCase):
    def test_only_language_bootstrap_is_disabled(self):
        result = adapt_language_navigation(BUNDLE)
        self.assertIn('function wc(', result)
        self.assertNotIn('wc({document$:gt});', result)
        self.assertIn('var Fc=vr(In.base);search();', result)
        self.assertIn('Ec({alert$:No});', result)
        self.assertIn(MARKER, result)
        self.assertEqual(adapt_language_navigation(result), result)

    def test_changed_theme_requires_review(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            adapt_language_navigation('function completelyDifferent(){}')
        with self.assertRaisesRegex(ValueError, 'found 2'):
            adapt_language_navigation(BUNDLE + 'wc({document$:other});')

    def test_only_theme_bundles_are_changed(self):
        with TemporaryDirectory() as temporary:
            site = Path(temporary)
            directory = site / 'assets/javascripts'
            directory.mkdir(parents=True)
            bundle = directory / 'bundle.test.min.js'
            other = directory / 'other.js'
            bundle.write_text(BUNDLE)
            other.write_text('untouched();')
            adapt_theme_assets(site)
            self.assertIn(MARKER, bundle.read_text())
            self.assertEqual(other.read_text(), 'untouched();')


if __name__ == '__main__':
    unittest.main()
