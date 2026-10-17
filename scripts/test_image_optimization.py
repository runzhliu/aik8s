"""Regression tests: python3 -m unittest discover -s scripts -p test_image_optimization.py."""

from html.parser import HTMLParser
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

try:
    from . import image_optimization as images
except ImportError:
    import image_optimization as images


def png(width=640, height=320):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress((b'\x00' + b'\x00' * width * 3) * height)) + chunk(b'IEND', b''))


def webp(kind, data):
    chunk = kind + struct.pack('<I', len(data)) + data + (b'\x00' if len(data) % 2 else b'')
    return b'RIFF' + struct.pack('<I', len(chunk) + 4) + b'WEBP' + chunk


def img_attrs(source):
    class Collector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.images = []

        def handle_starttag(self, tag, attrs):
            if tag == 'img':
                self.images.append(dict(attrs))

        handle_startendtag = handle_starttag

    parser = Collector()
    parser.feed(source)
    return parser.images


class ImageOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'site'
        self.root.mkdir()
        (self.root / 'assets').mkdir()
        (self.root / 'assets/p.png').write_bytes(png())
        self.page = self.root / 'posts/index.html'
        images._cached_dimensions.cache_clear()

    def optimize(self, source, root=None, page=None):
        return images.optimize_images(source, page or self.page, root or self.root)

    def test_dimensions_and_article_loading(self):
        source = ('<header><img src="/assets/p.png"></header><article>'
                  '<img src="/assets/p.png"><img src="/assets/p.png">'
                  '<img loading="eager" src="/assets/p.png">'
                  '<img fetchpriority="high" src="/assets/p.png">'
                  '<img class="photo no-lazy" src="/assets/p.png">'
                  '<aside><img src="/assets/p.png"></aside>'
                  '<img loading="lazy" decoding="sync" src="/assets/p.png"></article>')
        tags = img_attrs(self.optimize(source))
        for tag in tags:
            self.assertEqual((tag['width'], tag['height']), ('640', '320'))
        self.assertNotIn('loading', tags[0])
        self.assertNotIn('decoding', tags[0])
        self.assertNotIn('loading', tags[1])
        self.assertEqual(tags[1]['decoding'], 'async')
        self.assertEqual(tags[2]['loading'], 'lazy')
        self.assertEqual(tags[3]['loading'], 'eager')
        for index in (4, 5, 6):
            self.assertNotIn('loading', tags[index])
        self.assertEqual(tags[7]['decoding'], 'sync')
        self.assertEqual(tags[7]['loading'], 'lazy')

    def test_existing_first_lazy_and_no_article(self):
        self.assertEqual(img_attrs(self.optimize('<article><img loading=lazy src=/assets/p.png></article>'))[0]['loading'], 'lazy')
        for tag in img_attrs(self.optimize('<main><img src=/assets/p.png><img src=/assets/p.png></main>')):
            self.assertNotIn('loading', tag)
            self.assertNotIn('decoding', tag)

    def test_first_external_still_counts_as_content_first(self):
        source = '<article><img src="https://elsewhere.test/a.png"><img src="/assets/p.png"></article>'
        tags = img_attrs(self.optimize(source))
        self.assertEqual(tags[0], {'src': 'https://elsewhere.test/a.png'})
        self.assertEqual(tags[1]['loading'], 'lazy')

    def test_ignored_sources_unchanged(self):
        sources = ['data:image/png;base64,eA==', 'https://other.test/assets/p.png',
                   'http://aik8s.run/assets/p.png', 'https://aik8s.run:444/assets/p.png',
                   'https://aik8s.run@other.test/assets/p.png', '/missing.png', '',
                   'https://[invalid', '/assets/%00p.png', 'javascript:alert(1)', '#fragment']
        for src in sources:
            with self.subTest(src=src):
                source = f'<article><img src="{src}"><img src="{src}"></article>'
                self.assertEqual(self.optimize(source), source)

    def test_single_dimensions_and_css_intent(self):
        source = '<article>' + ''.join(f'<img src="/assets/p.png" {attrs}>' for attrs in (
            'width="200"', 'height="45"', 'width="10" height="12"',
            'width="100%"', 'height="auto"', 'width="12em"',
            'style="width: 100%; color:red"', 'width="24px"', 'width="0"',
        )) + '</article>'
        tags = img_attrs(self.optimize(source))
        self.assertEqual((tags[0]['width'], tags[0]['height']), ('200', '100'))
        self.assertEqual((tags[1]['width'], tags[1]['height']), ('90', '45'))
        self.assertEqual((tags[2]['width'], tags[2]['height']), ('10', '12'))
        for index in (3, 5, 8):
            self.assertNotIn('height', tags[index])
        self.assertNotIn('width', tags[4])
        self.assertNotIn('width', tags[6])
        self.assertNotIn('height', tags[6])
        self.assertEqual(tags[7]['height'], '12')

    def test_all_metadata_formats(self):
        jpeg = b'\xff\xd8\xff\xe0\x00\x04ab\xff\xc0' + struct.pack('>HBHHB', 11, 8, 320, 640, 1) + b'\x01\x11\x00\xff\xd9'
        cases = {
            'png': png(),
            'gif': b'GIF89a' + struct.pack('<HH', 640, 320) + b'\x00\x00\x00',
            'jpg': jpeg,
            'progressive.jpg': jpeg.replace(b'\xff\xc0', b'\xff\xc2'),
            'vp8.webp': webp(b'VP8 ', b'\x00\x00\x00\x9d\x01\x2a' + struct.pack('<HH', 640, 320)),
            'vp8l.webp': webp(b'VP8L', b'\x2f' + struct.pack('<I', 639 | (319 << 14))),
            'vp8x.webp': webp(b'VP8X', b'\x00' * 4 + (639).to_bytes(3, 'little') + (319).to_bytes(3, 'little')),
            'svg': b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320"/>',
            'viewbox.svg': b'<svg viewBox="0 0 640 320"/>',
            'single.svg': b'<svg width="640" viewBox="0,0,100,50"/>',
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                (self.root / 'assets' / name).write_bytes(data)
                tag = img_attrs(self.optimize(f'<img src="/assets/{name}">'))[0]
                self.assertEqual((tag['width'], tag['height']), ('640', '320'))

    def test_uncertain_and_malformed_metadata(self):
        cases = [b'<svg/>', b'<svg width="100%" viewBox="0 0 640 320"/>',
                 b'<svg viewBox="0 0 0 20"/>', b'<svg width="2em" height="4em"/>',
                 b'<!DOCTYPE svg [<!ENTITY x "640">]><svg width="&x;" height="320"/>',
                 '<!DOCTYPE svg [<!ENTITY x "640">]><svg width="&x;" height="320"/>'.encode('utf-16'),
                 b'<svg width="640" height="320">' + b' ' * images.MAX_METADATA_BYTES + b'</svg>',
                 b'\xff\xd8\xff\xe0\x00\x01', b'\x89PNG\r\n\x1a\n', b'GIF89a',
                 webp(b'VP8L', b'\x2f\x00\x00\x00\xe0'), png(0, 10), b'not an image']
        for data in cases:
            with self.subTest(data=data[:32]):
                (self.root / 'assets/bad').write_bytes(data)
                tag = img_attrs(self.optimize('<img src="/assets/bad">'))[0]
                self.assertNotIn('width', tag)
                self.assertNotIn('height', tag)

    def test_relative_query_fragment_unicode_and_absolute_urls(self):
        (self.root / 'assets/图.png').write_bytes(png())
        paths = ['../assets/p.png?x=1&amp;y=2#part', '/assets/p.png?v=2#x',
                 'https://aik8s.run/assets/p.png?x#y', '//aik8s.run/assets/p.png',
                 '/assets/%E5%9B%BE.png', '../assets/图.png']
        for path in paths:
            with self.subTest(path=path):
                source = f'<img src="{path}">'
                result = self.optimize(source)
                self.assertIn(f'src="{path}"', result)
                self.assertEqual(img_attrs(result)[0]['width'], '640')

    def test_chinese_and_english_nested_roots(self):
        english = self.root / 'en'
        (english / 'assets').mkdir(parents=True)
        (english / 'assets/p.png').write_bytes(png(120, 80))
        for root, page, paths, width in (
            (self.root, self.root / 'zh/嵌套/index.html', ['../../assets/p.png', '/assets/p.png'], '640'),
            (english, english / 'posts/deep/index.html', ['../../assets/p.png', '/assets/p.png', '/en/assets/p.png',
                                                       'https://aik8s.run/en/assets/p.png?x#y'], '120'),
            (self.root, self.page, ['/en/assets/p.png', 'https://aik8s.run/en/assets/p.png'], '120'),
        ):
            for path in paths:
                with self.subTest(root=root, path=path):
                    tag = img_attrs(self.optimize(f'<img src="{path}">', root, page))[0]
                    self.assertEqual(tag['width'], width)

    def test_root_traversal_and_symlinks(self):
        outside = Path(self.temp.name) / 'outside.png'
        outside.write_bytes(png())
        (self.root / 'assets/link.png').symlink_to(outside)
        for path in ('../../outside.png', '/%2e%2e/outside.png', '/assets/link.png',
                     '/assets/%2e%2e/%2e%2e/outside.png', '/assets/..%5c..%5coutside.png'):
            with self.subTest(path=path):
                source = f'<article><img src="{path}"></article>'
                self.assertEqual(self.optimize(source), source)
        # English builds must not read the Chinese output through ../.
        english = self.root / 'en'
        english.mkdir()
        self.assertEqual(self.optimize('<img src="../assets/p.png">', english, english / 'index.html'),
                         '<img src="../assets/p.png">')

    def test_preserves_source_and_is_idempotent(self):
        prefix = ('<!DOCTYPE html>\n<script>const html = "<img src=\\"/assets/p.png\\">"; '
                  'const x = "&amp;";</script>\n<script type="application/ld+json">'
                  '{"image":"<img src=/assets/p.png>"}</script><!-- <img src=/assets/p.png> -->\n')
        source = prefix + '<ARTICLE>\n<IMG\n SRC="/assets/p.png?a=1&amp;b=2#hash" ALT="&quot;图&quot;" />\n<img src=/assets/p.png></ARTICLE>'
        result = self.optimize(source)
        self.assertTrue(result.startswith(prefix))
        self.assertIn(' SRC="/assets/p.png?a=1&amp;b=2#hash" ALT="&quot;图&quot;" />', result)
        self.assertIn('<IMG width="640" height="320" decoding="async"\n', result)
        self.assertEqual(self.optimize(result), result)

    def test_text_containers_and_duplicate_attributes(self):
        source = '<article><textarea><img src="/assets/p.png"></article></textarea><img src="/assets/p.png"></article>'
        result = self.optimize(source)
        self.assertIn('<textarea><img src="/assets/p.png"></article></textarea>', result)
        self.assertNotIn('loading=', result)
        duplicate = '<img src="https://other.test/a.png" src="/assets/p.png">'
        self.assertEqual(self.optimize(duplicate), duplicate)
        local_duplicate = '<img src="/assets/p.png" src="https://other.test/a.png">'
        self.assertIn('width="640"', self.optimize(local_duplicate))

    def test_metadata_cached_and_read_bounded(self):
        original = images._metadata
        with patch.object(images, '_metadata', wraps=original) as reader:
            self.optimize('<img src=/assets/p.png><img src=/assets/p.png>')
            self.optimize('<img src=/assets/p.png>')
            self.assertEqual(reader.call_count, 1)
            (self.root / 'assets/p.png').write_bytes(png(200, 100))
            self.assertEqual(img_attrs(self.optimize('<img src=/assets/p.png>'))[0]['width'], '200')
            self.assertEqual(reader.call_count, 2)
        large = self.root / 'assets/large'
        large.write_bytes(b'?' * (images.MAX_METADATA_BYTES + 100))
        with patch.object(images, '_metadata', return_value=None) as reader:
            self.optimize('<img src=/assets/large>')
            self.assertEqual(len(reader.call_args.args[0]), images.MAX_METADATA_BYTES)


if __name__ == '__main__':
    unittest.main()
