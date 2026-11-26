"""Bounded static previews for local Assistant output."""
from html import escape
from html.parser import HTMLParser
import base64
import csv
from io import StringIO
from itertools import islice
import json
from struct import unpack
from xml.etree import ElementTree

MAX_INPUT = 16 * 1024 * 1024
MAX_PNG = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 8_000_000
MAX_TEXT = 24_000
_HTML_TAGS = frozenset('h1 h2 h3 p br ul ol li table tr td th b strong em i pre'.split())
_HTML_SKIP = frozenset('head script style iframe object svg canvas nav button template noscript'.split())
_SVG_TAGS = frozenset('svg g path line polyline polygon rect circle ellipse text tspan title desc defs clipPath'.split())
_SVG_ATTRS = frozenset(('viewBox width height x y x1 y1 x2 y2 d points cx cy r rx ry fill opacity '
                       'fill-opacity fill-rule stroke stroke-width stroke-opacity stroke-linecap '
                       'stroke-linejoin stroke-dasharray font-size font-family text-anchor transform').split())


def _png(data):
    if len(data) > MAX_PNG or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR' or len(data) < 24:
        raise ValueError('This PNG is unavailable for preview.')
    width, height = unpack('>II', data[16:24])
    if not width or not height or width * height > MAX_IMAGE_PIXELS:
        raise ValueError('This PNG is too large for preview.')
    return data


class _StaticReport(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fragments = []
        self.skipped = []
        self.remaining = MAX_TEXT
        self.png = None
        self._png_priority = -1
        self.svg = None
        self._svg_parts = None

    def _append(self, fragment):
        if len(fragment) <= self.remaining:
            self.fragments.append(fragment)
            self.remaining -= len(fragment)

    def handle_starttag(self, tag, attrs):
        if tag == 'svg' and not self.skipped and self.svg is None:
            self._svg_parts = []
        if self._svg_parts is not None:
            self._svg_parts.append(self.get_starttag_text())
            return
        if tag in _HTML_SKIP:
            self.skipped.append(tag)
        if self.skipped:
            return
        if tag in _HTML_TAGS:
            self._append('<' + tag + '>')
        if tag == 'img':
            properties = dict(attrs)
            src = properties.get('src') or ''
            caption = properties.get('alt') or ''
            # The Quick EMerge report starts with geometry. Prefer its sampled
            # S matrix over a template drawing when that result is available.
            priority = int(caption.startswith('S matrix magnitude;'))
            prefix = 'data:image/png;base64,'
            if priority > self._png_priority and src.startswith(prefix) and len(src) <= len(prefix) + 4 * ((MAX_PNG + 2) // 3):
                try:
                    self.png = _png(base64.b64decode(src[len(prefix):], validate=True))
                    self._png_priority = priority
                except ValueError:
                    pass

    def handle_startendtag(self, tag, attrs):
        if self._svg_parts is not None:
            self._svg_parts.append(self.get_starttag_text())
        else:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self._svg_parts is not None:
            self._svg_parts.append('</' + tag + '>')
            if tag == 'svg':
                try:
                    self.svg = _svg(''.join(self._svg_parts).encode('utf-8'))
                except (ValueError, ElementTree.ParseError):
                    pass
                self._svg_parts = None
            return
        if tag in self.skipped:
            del self.skipped[len(self.skipped) - 1 - self.skipped[::-1].index(tag):]
        elif not self.skipped and tag in _HTML_TAGS and tag != 'br':
            self._append('</' + tag + '>')

    def handle_data(self, data):
        if self._svg_parts is not None:
            self._svg_parts.append(escape(data))
        elif not self.skipped:
            self._append(escape(data[:self.remaining]))


def _svg(data):
    # Feed only inert drawing primitives to the native rasterizer.
    if len(data) > MAX_PNG or b'<!' in data or b'\x00' in data:
        raise ValueError('This SVG is unavailable for preview.')
    namespace = '{http://www.w3.org/2000/svg}'
    root = ElementTree.fromstring(data)
    if root.tag not in ('svg', namespace + 'svg'):
        raise ValueError('This SVG is unavailable for preview.')
    pending = [(root, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        name = node.tag.removeprefix(namespace)
        if count > 12_000 or depth > 32 or name not in _SVG_TAGS:
            raise ValueError('This SVG uses drawing features outside the preview limit.')
        node.tag = name
        pending.extend((child, depth + 1) for child in node)
        for key, value in list(node.attrib.items()):
            if key not in _SVG_ATTRS or 'url' in value.casefold():
                del node.attrib[key]
    root.set('xmlns', namespace[1:-1])
    return ElementTree.tostring(root, encoding='utf-8')


def _table(headers, rows):
    def row(values, tag):
        cells = ''.join(f'<{tag}>{escape(str(value)[:180])}</{tag}>' for value in values)
        return '<tr>' + cells + '</tr>'
    return ('<table border="1" cellspacing="0" cellpadding="4">' + row(headers, 'th')
            + ''.join(row(values, 'td') for values in rows) + '</table>')


def _json_preview(document):
    from wayricad_runtime.assistant_context import result_message

    value = document.get('result', document) if isinstance(document, dict) else document
    summary = result_message(value)
    if summary:
        return '<p>' + escape(summary) + '</p>'
    def scalar(item):
        return item is None or isinstance(item, (str, int, float, bool))
    def shown(item):
        return 'Unknown' if item is None else item
    markup = []
    if isinstance(value, dict):
        fields = [(key, shown(item)) for key, item in value.items()
                  if scalar(item) and key not in {'schema', 'source_sha256'}][:20]
        if fields:
            markup.append(_table(('Field', 'Value'), fields))
        frequencies = value.get('frequencies')
        if isinstance(frequencies, list):
            rows = []
            for sample in frequencies[:12]:
                if not isinstance(sample, dict):
                    continue
                try:
                    frequency = float(sample['frequency_hz'])
                    matrix = sample['z_ohm']
                    entries = [matrix[i][j] for i, j in ((0, 0), (0, 1), (1, 0), (1, 1))]
                    rows.append([f'{frequency:.6g}', *(f"{float(z['real']):.6g} {float(z['imag']):+.6g}j" for z in entries)])
                except (KeyError, TypeError, ValueError, IndexError, OverflowError):
                    continue
            if rows:
                markup.append('<h3>Two-port impedance</h3>'
                              + _table(('Frequency (Hz)', 'Z11 (Ω)', 'Z12 (Ω)', 'Z21 (Ω)', 'Z22 (Ω)'), rows))
        groups = ((key, item) for key, item in value.items() if isinstance(item, (list, dict)))
    elif isinstance(value, list):
        groups = iter([('Results', value)])
    else:
        return '<p>' + escape(str(shown(value))[:MAX_TEXT]) + '</p>'
    for name, group in islice(groups, 8):
        heading = '<h3>' + escape(name[:100]) + '</h3>'
        if isinstance(group, dict):
            fields = [(key, shown(item)) for key, item in group.items() if scalar(item)][:12]
            if fields:
                markup.append(heading + _table(('Field', 'Value'), fields))
            continue
        sample = group[:12]
        if sample and all(isinstance(row, dict) for row in sample):
            keys = list(dict.fromkeys(key for row in sample for key, item in row.items() if scalar(item)))[:7]
            if keys:
                markup.append(heading + _table(keys, ([shown(row.get(key)) for key in keys] for row in sample)))
        elif sample and all(scalar(item) for item in sample):
            markup.append(heading + _table(('Value',), ((shown(item),) for item in sample)))
        elif not group:
            markup.append(heading + '<p>No entries.</p>')
        if len(group) > len(sample):
            markup.append(f'<p>Showing up to {len(sample)} of {len(group)} entries in {escape(name[:100])}.</p>')
    return ''.join(markup)


def preview_content(path):
    with path.open('rb') as stream:
        data = stream.read(MAX_INPUT + 1)
    suffix = path.suffix.lower()
    truncated = len(data) > MAX_INPUT
    if truncated and suffix not in {'.html', '.htm'}:
        raise ValueError('This result is too large for a preview. Open the full report.')
    if suffix == '.png':
        return '', _png(data), None
    if suffix == '.svg':
        return '', None, _svg(data)
    if suffix == '.pdf':
        raise ValueError('Use Open selected report to inspect the full PDF.')
    text = data.decode('utf-8-sig', errors='replace')
    if suffix in {'.html', '.htm'}:
        report = _StaticReport()
        report.feed(text)
        report.close()
        content = ''.join(report.fragments)
        if truncated or report.remaining < MAX_TEXT // 2:
            content += '<p>Open the full report for complete results and interactive views.</p>'
        return content, report.png, None if report.png else report.svg
    if suffix == '.json':
        markup = _json_preview(json.loads(text))
        if markup:
            return markup + '<p>Open the full result for all data.</p>', None, None
        return '<p>Open the full result to inspect its numerical data.</p>', None, None
    if suffix == '.csv':
        reader = csv.reader(StringIO(text))
        headers = next(reader, [])
        if not headers:
            return '<p>No rows were exported.</p>', None, None
        rows = list(islice(reader, 31))
        note = '<p>Preview shows up to 30 rows and 10 columns.</p>' if len(rows) > 30 or len(headers) > 10 else ''
        return _table(headers[:10], (row[:10] for row in rows[:30])) + note, None, None
    return '<pre>' + escape(text[:MAX_TEXT]) + '</pre>', None, None


# Edge limits its in-memory navigation to 2 MiB. Keep larger images in the
# existing native preview, where they can be scaled without a data URL.
MAX_WEB_DOCUMENT = 1_900_000


def web_document(title, content, png=None, svg=None):
    """Wrap previously sanitized report content for an offline native WebView."""
    image = ''
    if png or svg:
        mime, data = ('image/png', png) if png else ('image/svg+xml', svg)
        if len(data) * 4 // 3 > MAX_WEB_DOCUMENT:
            return None
        encoded = base64.b64encode(data).decode('ascii')
        image = f'<figure><img src="data:{mime};base64,{encoded}" alt="Report figure"></figure>'
    policy = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
              "base-uri 'none'; form-action 'none'")
    page = ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
            f'<title>{escape(title)}</title>'
            '''<style>
            :root { color-scheme: light dark; font: 14px/1.55 system-ui, sans-serif }
            body { margin: 0; padding: 1rem 1.25rem; overflow-wrap: anywhere }
            h1, h2, h3 { line-height: 1.2; margin: 1em 0 .45em }
            h1 { font-size: 1.45rem; margin-top: 0 }
            h2 { font-size: 1.2rem }
            h3 { font-size: 1rem }
            table { border-collapse: collapse; width: 100%; margin: .6rem 0 1rem }
            th, td { padding: .45rem .6rem; text-align: left; border: 1px solid #80808055 }
            th { background: #80808022 }
            tr:nth-child(even) { background: #8080800b }
            figure { margin: 0 0 .85rem }
            img { display: block; max-width: 100%; max-height: 62vh; object-fit: contain }
            pre { white-space: pre-wrap }
            </style></head><body>'''
            + image + content + '</body></html>')
    return page if len(page.encode('utf-8')) <= MAX_WEB_DOCUMENT else None
