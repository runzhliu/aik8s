"""Add bounded, metadata-only image hints without reserializing generated HTML.

Call optimize_images after rendering a page. Paths are confined to site_dir;
URLs and all existing attributes are left byte-for-byte intact. No image pixels
are decoded. The first content image may get decoding=async (a decoding hint,
not deferred fetching), but never automatic loading=lazy.
"""

from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


MAX_METADATA_BYTES = 1024 * 1024
MAX_DIMENSION = 1_000_000
_NUMBER = re.compile(r'\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*', re.I)
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
         'link', 'meta', 'param', 'source', 'track', 'wbr'}
_EXCLUDED = {'header', 'aside', 'nav', 'footer', 'template'}
_TEXT_CONTAINERS = {'textarea', 'title', 'xmp', 'iframe', 'noembed', 'noframes'}


def _dimensions(width, height):
    if 0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION:
        return width, height
    return None


def _number(value):
    match = _NUMBER.fullmatch(value or '')
    if match:
        number = float(match[1])
        if 0 < number <= MAX_DIMENSION:
            return number
    return None


def _svg_dimensions(data):
    # Reject DTDs/entities rather than allowing XML entity expansion.
    if b'\x00' in data or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', data, re.I):
        return None
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return None
    if root.tag not in ('svg', '{http://www.w3.org/2000/svg}svg'):
        return None
    width, height = _number(root.get('width')), _number(root.get('height'))
    if width and height:
        return _dimensions(width, height)
    try:
        box = [float(part) for part in re.split(r'[\s,]+', root.get('viewBox', '').strip())]
        ratio = _dimensions(box[2], box[3]) if len(box) == 4 else None
    except ValueError:
        ratio = None
    if not ratio:
        return None
    # Percentage/physical-unit dimensions do not establish intrinsic pixels.
    if (root.get('width') is not None and width is None or
            root.get('height') is not None and height is None):
        return None
    return _dimensions(width or (height * ratio[0] / ratio[1] if height else ratio[0]),
                       height or (width * ratio[1] / ratio[0] if width else ratio[1]))


def _metadata(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        if len(data) >= 33 and data[8:16] == b'\x00\x00\x00\rIHDR':
            return _dimensions(*struct.unpack('>II', data[16:24]))
        return None
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return _dimensions(*struct.unpack('<HH', data[6:10])) if len(data) >= 13 else None
    if data.startswith(b'\xff\xd8'):
        pos = 2
        while pos < len(data):
            if data[pos] != 255:
                return None
            while pos < len(data) and data[pos] == 255:
                pos += 1
            if pos >= len(data):
                return None
            marker = data[pos]
            pos += 1
            if marker in (0xD9, 0xDA):
                return None
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                continue
            if pos + 2 > len(data):
                return None
            size = int.from_bytes(data[pos:pos + 2], 'big')
            if size < 2 or pos + size > len(data):
                return None
            if marker in (0xC0, 0xC1, 0xC2):
                if size < 8:
                    return None
                height, width = struct.unpack('>HH', data[pos + 3:pos + 7])
                return _dimensions(width, height)
            pos += size
        return None
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) >= 20:
        limit = min(len(data), int.from_bytes(data[4:8], 'little') + 8)
        pos = 12
        while pos + 8 <= limit:
            kind, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], 'little')
            start = pos + 8
            if start + size > limit:
                return None
            chunk = data[start:start + size]
            if kind == b'VP8X' and size == 10:
                return _dimensions(1 + int.from_bytes(chunk[4:7], 'little'),
                                   1 + int.from_bytes(chunk[7:10], 'little'))
            if kind == b'VP8 ' and size >= 10 and chunk[3:6] == b'\x9d\x01\x2a' and not chunk[0] & 1:
                width, height = struct.unpack('<HH', chunk[6:10])
                return _dimensions(width & 0x3fff, height & 0x3fff)
            if kind == b'VP8L' and size >= 5 and chunk[0] == 0x2f and not chunk[4] & 0xe0:
                bits = int.from_bytes(chunk[1:5], 'little')
                return _dimensions((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1)
            pos = start + size + size % 2
        return None
    return _svg_dimensions(data)


@lru_cache(maxsize=4096)
def _cached_dimensions(path, mtime_ns, size):
    del mtime_ns, size  # Cache key invalidates metadata after file changes.
    try:
        with path.open('rb') as stream:
            return _metadata(stream.read(MAX_METADATA_BYTES))
    except (OSError, ValueError, OverflowError):
        return None


def _local_image(src, html_path, site_dir):
    try:
        if not src or src != src.strip() or '\\' in src or any(ord(c) < 32 for c in src):
            return None
        url = urlsplit(src)
        if url.scheme or url.netloc:
            if (url.scheme not in ('', 'https') or url.hostname != 'aik8s.run' or
                    url.port not in (None, 443) or url.username or url.password):
                return None
        path = unquote(url.path, errors='strict')
        if not path or '\\' in path or any(ord(c) < 32 for c in path):
            return None
        root = site_dir.resolve()
        if path.startswith('/'):
            # English builds have their own root, while URLs retain /en/.
            if root.name == 'en' and path.startswith('/en/'):
                path = path[3:]
            candidate = root / path.lstrip('/')
        else:
            candidate = html_path.resolve().parent / path
        candidate = candidate.resolve()
        candidate.relative_to(root)
        if not candidate.is_file():
            return None
        return candidate
    except (OSError, ValueError, RuntimeError, UnicodeError):
        return None


def _format_dimension(value):
    return str(max(1, int(value + 0.5)))


class _ImageHints(HTMLParser):
    def __init__(self, source, html_path, site_dir):
        super().__init__(convert_charrefs=False)
        self.source, self.html_path, self.site_dir = source, html_path, site_dir
        self.offsets = [0]
        self.offsets.extend(match.end() for match in re.finditer('\n', source))
        self.stack = []
        self.seen_content_image = False
        self.edits = []

    def handle_starttag(self, tag, attrs):
        if any(item[0] in _TEXT_CONTAINERS for item in self.stack):
            return
        # Browsers retain the first occurrence of duplicate HTML attributes.
        attributes = {}
        for name, value in attrs:
            attributes.setdefault(name, value)
        classes = (attributes.get('class') or '').lower().split()
        excluded = (tag in _EXCLUDED or any(
            name in classes for name in ('logo', 'header', 'sidebar', 'no-lazy')) or
            attributes.get('role') in ('banner', 'navigation', 'complementary'))
        in_article = any(item[0] == 'article' for item in self.stack)
        content = in_article and not excluded and not any(item[1] for item in self.stack)
        if tag == 'img':
            first = not self.seen_content_image
            if content:
                self.seen_content_image = True
            self._image(attributes, content, first)
        elif tag not in _VOID:
            self.stack.append((tag, excluded))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] in _TEXT_CONTAINERS and tag != self.stack[-1][0]:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def _image(self, attrs, content, first):
        path = _local_image(attrs.get('src'), self.html_path, self.site_dir)
        if path is None:
            return
        additions = []
        try:
            stat = path.stat()
            dimensions = _cached_dimensions(path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            dimensions = None
        if dimensions and not re.search(r'(?:^|;)\s*(?:width|height)\s*:', attrs.get('style') or '', re.I):
            width, height = dimensions
            if 'width' not in attrs and 'height' not in attrs:
                additions.extend((('width', _format_dimension(width)), ('height', _format_dimension(height))))
            elif 'height' not in attrs and _number(attrs.get('width')):
                additions.append(('height', _format_dimension(_number(attrs['width']) * height / width)))
            elif 'width' not in attrs and _number(attrs.get('height')):
                additions.append(('width', _format_dimension(_number(attrs['height']) * width / height)))
        if content:
            if not first and 'loading' not in attrs and (attrs.get('fetchpriority') or '').lower() != 'high':
                additions.append(('loading', 'lazy'))
            if 'decoding' not in attrs:
                additions.append(('decoding', 'async'))
        if additions:
            line, column = self.getpos()
            start = self.offsets[line - 1] + column
            # Insert after the tag name, preserving every original attribute,
            # including unquoted values immediately followed by a slash.
            match = re.match(r'<img\b', self.get_starttag_text(), re.I)
            self.edits.append((start + match.end(), ''.join(f' {key}="{value}"' for key, value in additions)))


def optimize_images(source: str, html_path: Path, site_dir: Path) -> str:
    """Return source with safe local image dimensions and article loading hints.

    html_path is the generated HTML file (it need not exist yet); site_dir is
    the Chinese or English build root. Original src query/fragment and markup
    are untouched. Unsupported, missing and out-of-root images are ignored.
    """
    parser = _ImageHints(source, Path(html_path), Path(site_dir))
    parser.feed(source)
    parser.close()
    for position, addition in reversed(parser.edits):
        source = source[:position] + addition + source[position:]
    return source
