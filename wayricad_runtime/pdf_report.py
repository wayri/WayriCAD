"""Static PDF evidence from saved HTML reports, without a browser or JavaScript.

The exporter retains document text, tables and embedded PNG/JPEG figures. Canvas,
SVG and external images are listed as omissions rather than silently disappearing.
Install the optional ``reports`` extra in the interpreter doing the export.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
from html import escape, unescape
from html.parser import HTMLParser
import hashlib
import io
import json
from pathlib import Path
import re
import sys


MAX_HTML_BYTES = 32 * 1024 * 1024
MAX_NODES = 200_000
MAX_DEPTH = 256
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'wbr'}
_OMIT = {'script', 'style', 'noscript', 'nav', 'button', 'input', 'select', 'textarea', 'head'}
_DISPLAY_SUBSTITUTIONS = str.maketrans({'\u2192': ' -> ', '\u2190': ' <- ', '\u2194': ' <-> ',
                                       '\u2010': '-', '\u2011': '-', '\u2013': '-', '\u2014': '-'})


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


class _ReportParser(HTMLParser):
    """Bounded inert tree; attributes never become code or resource requests."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('document')
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > MAX_NODES or len(self.stack) > MAX_DEPTH:
            raise ValueError('Report HTML exceeds the PDF complexity limit.')
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.count += 1
        if self.count > MAX_NODES:
            raise ValueError('Report HTML exceeds the PDF complexity limit.')
        self.stack[-1].children.append(data)


def _plain(node):
    if isinstance(node, str):
        return node
    if node.tag in _OMIT or node.tag in {'canvas', 'svg', 'img'}:
        return ''
    text = ''.join(_plain(child) for child in node.children)
    return text + ('\n' if node.tag in {'p', 'div', 'br', 'li', 'tr', 'dt', 'dd'} else '')


def _markup(node):
    """Only trusted ReportLab inline tags survive; no HTML attributes survive."""
    if isinstance(node, str):
        return escape(node.translate(_DISPLAY_SUBSTITUTIONS))
    if node.tag in _OMIT or node.tag in {'canvas', 'svg', 'img'}:
        return ''
    text = ''.join(_markup(child) for child in node.children)
    if node.tag == 'br':
        return '<br/>'
    inline = {'strong': 'b', 'b': 'b', 'em': 'i', 'i': 'i', 'sub': 'sub', 'sup': 'super'}
    if node.tag in inline:
        return '<' + inline[node.tag] + '>' + text + '</' + inline[node.tag] + '>'
    return text


def _descendants(node, tags):
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag in tags:
                yield child
            elif child.tag not in _OMIT:
                yield from _descendants(child, tags)


def pdf_bytes(document, *, title='WayriCAD report', include_raw_evidence=False):
    """Render report semantics to PDF bytes; never execute scripts or load URLs.

    Inputs are bounded to 32 MiB and 200,000 parsed nodes. Wide tables are split
    into column panels with the first column repeated, not shrunk to illegibility.
    Interactive plots remain in HTML; the PDF lists omitted views explicitly.
    JSON-only preformatted evidence is summarized with a fingerprint unless
    ``include_raw_evidence`` explicitly requests the raw data.
    """
    if not isinstance(document, str):
        raise ValueError('PDF input must be HTML text.')
    if len(document.encode('utf-8')) > MAX_HTML_BYTES:
        raise ValueError('Report HTML exceeds the 32 MiB PDF input limit.')
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, Image
        from reportlab.platypus.doctemplate import LayoutError
        import reportlab
    except ImportError as exc:
        raise RuntimeError('PDF export needs reportlab in this interpreter. Install wayricad[reports], or use the HTML Print / save as PDF control.') from exc
    fonts = Path(reportlab.__file__).parent / 'fonts'
    if 'WayriReport' not in pdfmetrics.getRegisteredFontNames():
        for name, filename in (('WayriReport', 'Vera.ttf'), ('WayriReport-Bold', 'VeraBd.ttf'),
                               ('WayriReport-Italic', 'VeraIt.ttf'), ('WayriReport-BoldItalic', 'VeraBI.ttf')):
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
        pdfmetrics.registerFontFamily('WayriReport', normal='WayriReport', bold='WayriReport-Bold',
                                      italic='WayriReport-Italic', boldItalic='WayriReport-BoldItalic')
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = 'WayriReport'
        style.textColor = colors.HexColor('#203744')
        style.wordWrap = 'CJK'  # Break long net names/hashes without clipping.
    styles['BodyText'].fontSize = 9
    styles['BodyText'].leading = 13
    styles['BodyText'].spaceAfter = 7
    for name, size in (('Title', 21), ('Heading1', 17), ('Heading2', 13), ('Heading3', 11)):
        styles[name].fontName = 'WayriReport-Bold'
        styles[name].fontSize = size
        styles[name].leading = size * 1.25
    cell_style = ParagraphStyle('ReportCell', parent=styles['BodyText'], fontSize=8, leading=11,
                                spaceAfter=0, alignment=TA_LEFT)
    note_style = ParagraphStyle('ReportNote', parent=styles['BodyText'], textColor=colors.HexColor('#526976'), fontSize=8)
    parser = _ReportParser()
    parser.feed(document)
    parser.close()
    story = []
    omissions = []
    page_width, page_height = A4
    available_width = page_width - 84

    def paragraph(text, style='BodyText'):
        if text.strip():
            story.append(Paragraph(text, styles[style] if isinstance(style, str) else style))

    def raster(node):
        source = node.attrs.get('src') or ''
        match = re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)', source, re.I)
        description = node.attrs.get('alt') or 'Unlabelled figure'
        if not match:
            omissions.append('External or unsupported image: ' + description)
            return
        if len(match[2]) > MAX_IMAGE_BYTES * 4 // 3 + 1024:
            raise ValueError('Embedded report image exceeds the 8 MiB limit.')
        try:
            raw = base64.b64decode(re.sub(r'\s+', '', match[2]), validate=True)
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError('Embedded report image exceeds the 8 MiB limit.')
            from PIL import Image as PillowImage
            with PillowImage.open(io.BytesIO(raw)) as checked:
                width, height = checked.size
                if checked.format not in {'PNG', 'JPEG'} or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError('Embedded report image has unsupported format or exceeds 25 million pixels.')
                checked.verify()
            image = Image(io.BytesIO(raw))
            scale = min(available_width / width, (page_height - 150) / height, 1)
            image.drawWidth = width * scale
            image.drawHeight = height * scale
            story.extend([image, Spacer(1, 5)])
            paragraph(escape(description), note_style)
        except (OSError, ValueError, PillowImage.DecompressionBombError) as exc:
            raise ValueError('Invalid embedded report image: ' + str(exc)) from exc

    def table(node):
        for view in _descendants(node, {'canvas', 'svg', 'iframe', 'object', 'embed', 'video', 'audio', 'img'}):
            if view.tag == 'img':
                omissions.append('Figure inside table: ' + (view.attrs.get('alt') or 'Unlabelled figure'))
            else:
                omissions.append(view.tag.upper() + ': ' + (view.attrs.get('aria-label') or view.attrs.get('title') or view.attrs.get('id') or 'interactive table view'))
        rows = list(_descendants(node, {'tr'}))
        if len(rows) > 10_000:
            raise ValueError('A PDF table exceeds the 10,000-row limit.')
        data = []
        header = False
        merged = False
        carried = {}
        for row in rows:
            cells = [child for child in row.children if isinstance(child, _Node) and child.tag in {'th', 'td'}]
            if not cells:
                continue
            if not data:
                header = all(cell.tag == 'th' for cell in cells)
            values = []
            column = 0
            for cell in cells:
                merged = merged or cell.attrs.get('rowspan', '1') != '1' or cell.attrs.get('colspan', '1') != '1'
                while carried.get(column, 0):
                    values.append('')
                    carried[column] -= 1
                    column += 1
                try:
                    span = int(cell.attrs.get('colspan', '1'))
                    row_span = int(cell.attrs.get('rowspan', '1'))
                except ValueError:
                    raise ValueError('A PDF table cell has an invalid span.')
                if not 1 <= span <= 64 or not 1 <= row_span <= 10_000:
                    raise ValueError('A PDF table cell has an invalid column span.')
                if any(carried.get(index, 0) for index in range(column, column + span)):
                    raise ValueError('A PDF table contains overlapping merged cells.')
                values.extend([_markup(cell)] + [''] * (span - 1))
                if row_span > 1:
                    for index in range(column, column + span):
                        carried[index] = row_span - 1
                column += span
            while carried.get(column, 0):
                values.append('')
                carried[column] -= 1
                column += 1
            if len(values) > 64:
                raise ValueError('A PDF table exceeds the 64-column limit.')
            data.append(values)
        if not data:
            return
        if merged:
            paragraph('Merged HTML table cells are flattened here; consult the HTML report for grouped column and row headings.', note_style)
        columns = max(map(len, data))
        for row in data:
            row.extend([''] * (columns - len(row)))
        # Six columns per panel keeps an A4 portrait report readable. Repeat the
        # identifying first column on every continuation panel.
        panels = [list(range(columns))] if columns <= 6 else [[0] + list(range(start, min(start + 5, columns))) for start in range(1, columns, 5)]
        for number, panel in enumerate(panels, 1):
            if len(panels) > 1:
                paragraph('Table columns ' + ', '.join(str(column + 1) for column in panel) +
                          ' (panel ' + str(number) + ' of ' + str(len(panels)) + ')', note_style)
            values = [[Paragraph(('<b>' + (row[column] or ' ') + '</b>') if header and index == 0 else (row[column] or ' '), cell_style)
                       for column in panel] for index, row in enumerate(data)]
            weights = []
            for column in panel:
                lengths = sorted(len(unescape(re.sub(r'<[^>]*>', '', row[column]))) for row in data)
                # A representative long cell makes evidence columns useful,
                # without allowing one pathological row to consume the table.
                length = lengths[min(len(lengths) - 1, int(len(lengths) * .9))]
                weights.append(min(72, max(12, length)))
            # Reserve enough width for short status/header words before giving
            # long evidence fields their larger share of the remaining space.
            minimum = min(54, available_width / len(panel))
            remainder = available_width - minimum * len(panel)
            widths = [minimum + remainder * weight / sum(weights) for weight in weights]
            rendered = LongTable(values, colWidths=widths,
                                 repeatRows=1 if header else 0, splitByRow=1, splitInRow=1,
                                 hAlign='LEFT', spaceAfter=14)
            commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ('LINEBELOW', (0, 0), (-1, -1), .4, colors.HexColor('#d4e0e5'))]
            if header:
                commands.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eaf2f5')))
            rendered.setStyle(TableStyle(commands))
            story.append(rendered)

    def walk(node):
        if isinstance(node, str):
            paragraph(escape(node))
            return
        if node.tag in _OMIT:
            return
        if node.tag in {'canvas', 'svg', 'iframe', 'object', 'embed', 'video', 'audio'}:
            description = node.tag.upper() + ': ' + (node.attrs.get('aria-label') or node.attrs.get('title') or node.attrs.get('id') or 'interactive view')
            omissions.append(description)
            paragraph('View available in the HTML report: ' + escape(description), note_style)
            return
        if node.tag == 'img':
            raster(node)
            return
        if node.tag == 'table':
            table(node)
            return
        if node.tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            paragraph(_markup(node), {'h1': 'Heading1', 'h2': 'Heading2'}.get(node.tag, 'Heading3'))
            return
        if node.tag == 'pre':
            content = _plain(node)
            if not include_raw_evidence:
                try:
                    parsed = json.loads(content)
                except ValueError:
                    parsed = None
                if isinstance(parsed, (dict, list)):
                    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
                    paragraph('Raw JSON evidence retained in the HTML report; not expanded in this PDF. '
                              'Keep the companion evidence JSON when supplied. Use --include-raw-evidence to include the raw data.', note_style)
                    paragraph(str(len(content)) + ' characters. SHA256 of the exact decoded HTML preformatted '
                              'text (UTF-8): ' + digest, note_style)
                    return
            # Paragraphs wrap large JSON/hash evidence instead of clipping it.
            for line in content.splitlines():
                paragraph(escape(line), note_style)
            return
        if node.tag in {'p', 'li', 'dt', 'dd', 'summary', 'figcaption', 'blockquote'}:
            paragraph(('&#8226; ' if node.tag == 'li' else '') + _markup(node))
            # Figures sometimes sit inside a paragraph; retain those separately.
            for image in _descendants(node, {'img', 'canvas', 'svg'}):
                walk(image)
            return
        # A div often contains plain inline text rather than paragraph children.
        pending = []
        for child in node.children:
            if isinstance(child, str) or child.tag in {'span', 'a', 'b', 'strong', 'i', 'em', 'code', 'br', 'sub', 'sup'}:
                pending.append(_markup(child))
            else:
                paragraph(''.join(pending)); pending = []
                walk(child)
        paragraph(''.join(pending))

    paragraph(escape(title), 'Title')
    paragraph('Static report export. Text, tables and embedded raster figures are retained. '
              'Use the HTML report for interactive selection, probes and 3D views.', note_style)
    walk(parser.root)
    if omissions:
        paragraph('Views retained in the HTML report', 'Heading2')
        paragraph('These views cannot be reproduced by the static exporter. Their omission does not imply that the corresponding analysis is complete.', note_style)
        for item in dict.fromkeys(omissions):
            paragraph(escape(item), note_style)
    if not story:
        paragraph('No printable report content.')
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=42, leftMargin=42,
                            topMargin=42, bottomMargin=45, title=title, author='WayriCAD')

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#d4e0e5'))
        canvas.line(42, 34, page_width - 42, 34)
        canvas.setFont('WayriReport', 8)
        canvas.setFillColor(colors.HexColor('#526976'))
        canvas.drawString(42, 22, 'WayriCAD | Static report')
        canvas.drawRightString(page_width - 42, 22, 'Page ' + str(doc.page))
        canvas.restoreState()

    try:
        pdf.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    except LayoutError as exc:
        raise ValueError('Report content cannot fit the static PDF layout; use HTML Print / save as PDF for this report. ' + str(exc)) from exc
    return buffer.getvalue()


def export_pdf(source, destination, *, evidence=None, include_raw_evidence=False):
    """Export saved HTML to a distinct PDF, checking optional source evidence.

    HTML, evidence JSON, board and study files are protected against aliasing.
    The existing destination is retained if parsing, rendering or publication
    fails. External resources and scripts are never opened or evaluated.
    """
    from .report_ui import checked_sources, publish_documents
    source = Path(source)
    destination = Path(destination)
    if source.suffix.lower() not in {'.html', '.htm'}:
        raise ValueError('PDF export requires a saved HTML report.')
    if destination.suffix.lower() != '.pdf':
        raise ValueError('Choose a .pdf report destination, not a design or evidence file.')
    if source.stat().st_size > MAX_HTML_BYTES:
        raise ValueError('Report HTML exceeds the 32 MiB PDF input limit.')
    protected = [source]
    evidence_bytes = None
    if evidence is not None:
        evidence = Path(evidence)
        if evidence.stat().st_size > MAX_HTML_BYTES:
            raise ValueError('Report evidence exceeds the 32 MiB input limit.')
        evidence_bytes = evidence.read_bytes()
        bundle = json.loads(evidence_bytes.decode('utf-8'))
        if not isinstance(bundle, dict):
            raise ValueError('Report evidence must be a JSON object.')
        protected.extend([evidence, *checked_sources(bundle)])
    document_bytes = source.read_bytes()
    document = document_bytes.decode('utf-8')
    data = pdf_bytes(document, title=source.stem.replace('-', ' ').replace('_', ' '),
                     include_raw_evidence=include_raw_evidence)
    if source.read_bytes() != document_bytes:
        raise ValueError('HTML report changed during PDF export; export the report again.')
    if evidence is not None:
        if evidence.read_bytes() != evidence_bytes:
            raise ValueError('Report evidence changed during PDF export; export the report again.')
        checked_sources(bundle)
    publish_documents({destination: data}, sources=protected)
    return {'pdf': str(destination), 'html': str(source)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Saved HTML report; no scripts or remote resources are loaded.')
    parser.add_argument('--output', type=Path, required=True, help='Destination .pdf file.')
    parser.add_argument('--evidence', type=Path, help='Optional companion JSON; verify declared board/study hashes before exporting.')
    parser.add_argument('--include-raw-evidence', action='store_true', help='Expand raw JSON evidence instead of retaining it in HTML with a fingerprint summary.')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export_pdf(args.input, args.output, evidence=args.evidence,
                                    include_raw_evidence=args.include_raw_evidence), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'status': 'ERROR', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
