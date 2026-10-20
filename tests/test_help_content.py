"""Check that every active plugin ships usable, self-contained help navigation."""
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class HelpDocument(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.images = []
        self.ids = []
        self.remote_dependencies = []
        self.headings = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a' and 'href' in attrs:
            self.links.append(attrs['href'])
        if tag == 'img':
            self.images.append(attrs.get('src', ''))
        if tag in ('h1', 'h2', 'h3'):
            self.headings += 1
        dependency = attrs.get('src') if tag in ('script', 'iframe') else None
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            dependency = attrs.get('href')
        if dependency and (urlsplit(dependency).scheme or dependency.startswith('//')):
            self.remote_dependencies.append(dependency)


class OfflineHelpTests(unittest.TestCase):
    def documents(self):
        for metadata in sorted(ROOT.glob('*_plugin/metadata.json')):
            json.loads(metadata.read_text(encoding='utf-8-sig'))
            path = metadata.with_name('help.html')
            self.assertTrue(path.is_file(), str(path))
            text = path.read_text(encoding='utf-8-sig')
            document = HelpDocument()
            document.feed(text)
            yield path, text, document

    def test_each_active_plugin_has_local_workflow_illustrations(self):
        for path, text, document in self.documents():
            with self.subTest(plugin=path.parent.name):
                self.assertIn('WayriCAD', text)
                self.assertGreaterEqual(document.headings, 3)
                self.assertTrue(document.images, 'Ship a local workflow illustration')
                self.assertFalse(document.remote_dependencies, 'Help must work without a network')
                for image in document.images:
                    target = urlsplit(image)
                    self.assertFalse(target.scheme or target.netloc, image)
                    self.assertTrue((path.parent / unquote(target.path)).is_file(), image)
                    self.assertIn(Path(unquote(target.path)).name,
                                  [p.name for p in (path.parent / unquote(target.path)).parent.iterdir()])

    def test_contents_anchors_are_unique_and_resolvable(self):
        for path, _, document in self.documents():
            with self.subTest(plugin=path.parent.name):
                self.assertEqual(len(document.ids), len(set(document.ids)))
                for link in document.links:
                    target = urlsplit(link)
                    if not target.path and target.fragment:
                        self.assertIn(unquote(target.fragment), document.ids, link)

    def test_help_index_covers_each_active_package_once(self):
        index = (ROOT / 'docs/HELP_INDEX.md').read_text(encoding='utf-8')
        for metadata in sorted(ROOT.glob('*_plugin/metadata.json')):
            target = f'../{metadata.parent.name}/help.html'
            self.assertEqual(index.count(f']({target})'), 1, target)
            guide = next(p.name for p in metadata.parent.iterdir()
                         if p.name.lower() == 'readme.md')
            self.assertIn(f'](../{metadata.parent.name}/{guide})', index)


if __name__ == '__main__':
    unittest.main()
