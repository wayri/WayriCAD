"""Bounded plain Markdown editing, clipboard conversion and inert local preview."""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import quote, urlsplit

MAX_TEXT = 16000
MAX_HTML = 128000
MAX_NODES = 4096
MAX_DEPTH = 64
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_IGNORE = {'script', 'style', 'head', 'noscript', 'template', 'iframe', 'object', 'svg', 'math'}


def _text(value):
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise ValueError('Messages must contain at most 16,000 characters.')
    if any(ord(c) < 32 and c not in '\t\r\n' or ord(c) == 127 for c in value):
        raise ValueError('Message contains unsupported control characters.')
    return value


def safe_https(value):
    """Return a Markdown-safe HTTPS URL, or reject a non-web/ambiguous target."""
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or any(c in value for c in '\\<>"\'')):
        raise ValueError('Use a complete HTTPS link without credentials or whitespace.')
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        parsed.port
    except ValueError:
        raise ValueError('Use a complete HTTPS link without credentials or whitespace.') from None
    return quote(value, safe=':/?#@!$&*+,;=%~._-')


def _code(value, block=False):
    longest = max((len(match.group()) for match in re.finditer(r'`+', value)), default=0)
    fence = '`' * max(3 if block else 1, longest + 1)
    if block:
        return fence + '\n' + value + '\n' + fence, len(fence) + 1
    padding = ' ' if value.startswith(('`', ' ')) or value.endswith(('`', ' ')) else ''
    return fence + padding + value + padding + fence, len(fence) + len(padding)


def apply_format(text, start, end, action, *, url=None):
    """Return ``(text, start, end)`` using Python character selection offsets.

    Inline actions select the formatted content; line actions select the entire
    replacement block. No HTML or separate rich-text state is stored.
    """
    _text(text)
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
        raise ValueError('Selection must be valid character bounds within the message.')
    if action not in {'bold', 'italic', 'inlinecode', 'codeblock', 'heading', 'quote',
                       'bullets', 'numbered', 'tasks', 'link', 'table'}:
        raise ValueError('Unknown Markdown formatting action.')
    left, right = start, end
    selected = text[start:end]
    offset = 0
    content_length = None
    if action in ('bold', 'italic'):
        selected = selected or ('bold text' if action == 'bold' else 'italic text')
        marker = '**' if action == 'bold' else '*'
        replacement = marker + selected + marker
        offset, content_length = len(marker), len(selected)
    elif action == 'inlinecode':
        selected = selected or 'code'
        if '\n' in selected or '\r' in selected:
            raise ValueError('Use a code block for a multiline selection.')
        replacement, offset = _code(selected)
        content_length = len(selected)
    elif action == 'link':
        selected = selected or 'link text'
        label = selected.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
        replacement = '[' + label + '](' + safe_https(url or 'https://example.com') + ')'
        offset, content_length = 1, len(label)
    else:
        # Block commands operate on complete touched lines, preserving surrounding text.
        left = text.rfind('\n', 0, start) + 1
        endpoint = end - 1 if end > start and text[end - 1:end] == '\n' else end
        right = text.find('\n', endpoint)
        if right < 0:
            right = len(text)
        selected = text[left:right]
        if action == 'codeblock':
            replacement, offset = _code(selected or 'code', block=True)
            content_length = len(selected or 'code')
        elif action == 'table':
            if not selected:
                replacement = '| Column 1 | Column 2 |\n| --- | --- |\n| Value | Value |'
            else:
                rows = [line.split('\t') if '\t' in line else [line] for line in selected.split('\n')]
                columns = max(map(len, rows))
                if columns > 16:
                    raise ValueError('A composer table supports at most 16 columns.')
                def row(values):
                    return '| ' + ' | '.join(value.replace('|', '\\|') for value in values + [''] * (columns - len(values))) + ' |'
                replacement = '\n'.join([row(rows[0]), row(['---'] * columns), *[row(values) for values in rows[1:]]])
        else:
            lines = (selected or ('Heading' if action == 'heading' else 'Item')).split('\n')
            prefixes = {'heading': '# ', 'quote': '> ', 'bullets': '- ', 'tasks': '- [ ] '}
            replacement = '\n'.join((str(i + 1) + '. ' if action == 'numbered' else prefixes[action]) + line
                                    for i, line in enumerate(lines))
    updated = _text(text[:left] + replacement + text[right:])
    if content_length is None:
        return updated, left, left + len(replacement)
    return updated, left + offset, left + offset + content_length


def _literal(value):
    return re.sub(r'([\\`*_{}\[\]<>#+.!|~-])', r'\\\1', value)


class _Clipboard(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': '', 'children': [], 'ignored': False}
        self.stack = [self.root]
        self.nodes = 0
        self.characters = 0

    def _count(self):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError('Clipboard HTML contains too many elements.')

    def handle_starttag(self, tag, attrs):
        self._count()
        if len(self.stack) > MAX_DEPTH:
            raise ValueError('Clipboard HTML is nested too deeply.')
        node = dict(tag=tag, children=[], ignored=self.stack[-1]['ignored'] or tag in _IGNORE)
        if tag == 'a':
            try:
                node['url'] = safe_https(dict(attrs).get('href'))
            except ValueError:
                node['url'] = None
        if tag == 'img':
            node['alt'] = dict(attrs).get('alt', '')
        if not node['ignored']:
            self.stack[-1]['children'].append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        self._count()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self._count()
        if self.stack[-1]['ignored']:
            return
        self.characters += len(data)
        if self.characters > MAX_TEXT:
            raise ValueError('Pasted text exceeds 16,000 characters.')
        self.stack[-1]['children'].append(data)


def _plain(node):
    if isinstance(node, str):
        return node
    if node['tag'] == 'br':
        return '\n'
    return ''.join(_plain(child) for child in node['children'])


def _join(parts):
    result = ''
    for part in parts:
        if result.endswith('\n') and part.startswith('\n'):
            result = result.rstrip('\n') + '\n\n' + part.lstrip('\n')
        else:
            result += part
    return result


def _markdown(node):
    if isinstance(node, str):
        return _literal(node)
    tag = node['tag']
    if tag in ('code', 'pre'):
        return ('\n\n' if tag == 'pre' else '') + _code(_plain(node).strip('\n'), block=tag == 'pre')[0] + ('\n\n' if tag == 'pre' else '')
    if tag in ('ul', 'ol'):
        items = []
        for child in node['children']:
            content = _markdown(child).strip('\n')
            if not content.strip():
                continue
            marker = str(len(items) + 1) + '. ' if tag == 'ol' else '- '
            items.append(marker + content.replace('\n', '\n' + ' ' * len(marker)))
        return '\n\n' + '\n'.join(items) + '\n\n'
    content = _join(_markdown(child) for child in node['children'])
    if tag in ('strong', 'b', 'em', 'i'):
        marker = '**' if tag in ('strong', 'b') else '*'
        match = re.fullmatch(r'(\s*)(.*?)(\s*)', content, re.S)
        return match[1] + (marker + match[2] + marker if match[2] else '') + match[3]
    if tag == 'a' and node.get('url'):
        return '[' + content + '](' + node['url'] + ')'
    if tag == 'br':
        return '\n'
    if tag == 'img':
        return _literal('[Image: ' + node.get('alt', '') + ']') if node.get('alt') else ''
    if tag == 'blockquote':
        return '\n\n' + '\n'.join('> ' + line for line in content.strip().split('\n')) + '\n\n'
    if re.fullmatch(r'h[1-6]', tag):
        return '\n\n' + '#' * int(tag[1]) + ' ' + content.strip() + '\n\n'
    if tag in ('p', 'div', 'section', 'article', 'li'):
        return '\n\n' + content.strip() + '\n\n'
    return content


def html_to_markdown(value):
    """Convert bounded clipboard HTML to visible Markdown without fetching assets."""
    if not isinstance(value, str) or len(value) > MAX_HTML:
        raise ValueError('Clipboard HTML exceeds 128,000 characters.')
    parser = _Clipboard()
    try:
        parser.feed(value)
        parser.close()
        result = _markdown(parser.root)
    except RecursionError:
        raise ValueError('Clipboard HTML is nested too deeply.') from None
    return _text(result.strip())


def _inline(value, depth=0):
    if depth > 12:
        return escape(value)
    parts = []
    index = 0
    while index < len(value):
        if value[index] == '\\' and index + 1 < len(value):
            parts.append(escape(value[index + 1])); index += 2; continue
        if value[index] == '`':
            count = len(value[index:]) - len(value[index:].lstrip('`'))
            marker = '`' * count
            match = re.search(r'(?<!`)' + re.escape(marker) + r'(?!`)', value[index + count:])
            if match:
                end = index + count + match.start()
                content = value[index + count:end]
                if content.startswith(' ') and content.endswith(' ') and content.strip():content = content[1:-1]
                parts.append('<code>' + escape(content) + '</code>'); index = end + count; continue
        image = value.startswith('![', index)
        if image or value[index] == '[':
            begin = index + (2 if image else 1)
            match = re.match(r'((?:\\.|[^\]\\])*)\]\(([^\s)]*)\)', value[begin:])
            if match:
                label, url = match.groups()
                if image:
                    parts.append('<span>[Image: ' + escape(label) + ']</span>')
                else:
                    try:
                        url = safe_https(url)
                    except ValueError:
                        parts.append(escape(value[index:begin + match.end()]))
                    else:
                        parts.append('<span class="md-link">' + _inline(label, depth + 1) + '</span> (' + escape(url) + ')')
                index = begin + match.end(); continue
        formatted = False
        for marker, opening, closing in (('***', '<strong><em>', '</em></strong>'),
                ('**', '<strong>', '</strong>'), ('__', '<strong>', '</strong>'),
                ('*', '<em>', '</em>'), ('_', '<em>', '</em>')):
            if value.startswith(marker, index):
                end = value.find(marker, index + len(marker))
                if end > index + len(marker):
                    parts.append(opening + _inline(value[index + len(marker):end], depth + 1) + closing)
                    index = end + len(marker); formatted = True; break
        if not formatted:
            parts.append(escape(value[index])); index += 1
    return ''.join(parts)


def _cells(line):
    values = re.split(r'(?<!\\)\|', line.strip())
    if len(values) > 1 and not values[0]:values.pop(0)
    if len(values) > 1 and not values[-1]:values.pop()
    return [value.strip() for value in values]


def preview_html(text):
    """Render a small Markdown subset as inert HTML: no href/src or raw HTML."""
    _text(text)
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    output = []
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = re.fullmatch(r' {0,3}(`{3,}|~{3,})[^`~]*', line)
        if fence:
            marker = fence[1]; index += 1; code = []
            while index < len(lines) and not re.fullmatch(r' {0,3}' + re.escape(marker[0]) + '{' + str(len(marker)) + r',}\s*', lines[index]):
                code.append(lines[index]); index += 1
            output.append('<pre><code>' + escape('\n'.join(code)) + '</code></pre>'); index += 1; continue
        if index + 1 < len(lines) and '|' in line:
            header, separator = _cells(line), _cells(lines[index + 1])
            if len(header) == len(separator) and len(header) <= 16 and all(re.fullmatch(r':?-{3,}:?', cell) for cell in separator):
                rows = []; index += 2
                while index < len(lines) and '|' in lines[index] and len(_cells(lines[index])) == len(header):
                    rows.append(_cells(lines[index])); index += 1
                output.append('<table><tr>' + ''.join('<th>' + _inline(cell) + '</th>' for cell in header) + '</tr>' +
                    ''.join('<tr>' + ''.join('<td>' + _inline(cell) + '</td>' for cell in row) + '</tr>' for row in rows) + '</table>')
                continue
        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        if heading:
            level = str(len(heading[1])); output.append('<h' + level + '>' + _inline(heading[2]) + '</h' + level + '>')
        elif line.startswith('> '):
            quoted = []
            while index < len(lines) and lines[index].startswith('> '):
                quoted.append(_inline(lines[index][2:])); index += 1
            output.append('<blockquote>' + '<br>'.join(quoted) + '</blockquote>'); continue
        elif re.match(r'^\s*(?:[-+*]|\d+[.)])\s+', line):
            ordered = bool(re.match(r'^\s*\d+[.)]\s+', line)); tag = 'ol' if ordered else 'ul'; items = []
            pattern = r'^\s*\d+[.)]\s+(.*)$' if ordered else r'^\s*[-+*]\s+(.*)$'
            while index < len(lines):
                match = re.match(pattern, lines[index])
                if not match:break
                content = match[1]
                task = re.match(r'^\[([ xX])\]\s+(.*)$', content)
                items.append('<li>' + (('☑ ' if task[1].lower() == 'x' else '☐ ') + _inline(task[2]) if task else _inline(content)) + '</li>')
                index += 1
            output.append('<' + tag + '>' + ''.join(items) + '</' + tag + '>'); continue
        elif line:
            output.append('<p>' + _inline(line) + '</p>')
        index += 1
    return '<html><body>' + ''.join(output) + '</body></html>'
