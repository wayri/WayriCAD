"""Check current user documentation and the local images shipped in PCM packages."""
import argparse
from html.parser import HTMLParser
import json
from io import BytesIO
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import unquote, urlsplit
import zipfile
import xml.etree.ElementTree as ET
import sys

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '.build-tools').is_dir():sys.path.insert(0, str(ROOT / '.build-tools'))
from PIL import Image


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.images = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ('href', 'src'):
            if key in attrs:self.links.append(attrs[key])
        if tag == 'img' and 'src' in attrs:self.images.append(attrs['src'])


def references(text):
    parser = Links(); parser.feed(text)
    markdown = re.findall(r'(!?)\[[^\]]*\]\(([^)]+)\)', text)
    for image, target in markdown:
        target = target.strip().split(' "', 1)[0].strip('<>')
        parser.links.append(target)
        if image:parser.images.append(target)
    return parser.links, parser.images


def local_path(url):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:return None
    return unquote(parsed.path)


def image_valid(data, suffix):
    try:
        if suffix.lower() == '.svg':return ET.fromstring(data).tag.split('}')[-1] == 'svg'
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
        return True
    except (OSError, ValueError, ET.ParseError):return False


def check_document(label, text, read, *, require_image=False, check_links=True, name=''):
    errors = []; links, images = references(text)
    local_images = [p for url in images if (p := local_path(url))]
    if require_image and not any(PurePosixPath(p).stem not in ('icon','icon_dark') for p in local_images):errors.append(f'{label}: add a local application illustration')
    for target in set([p for url in links if (p := local_path(url))] if check_links else local_images):
        try:data = read(target)
        except (OSError, KeyError, ValueError):
            errors.append(f'{label}: missing local target {target}');continue
        if target in local_images and not image_valid(data, PurePosixPath(target).suffix):
            errors.append(f'{label}: invalid or unsupported image {target}')
    titles = re.findall(r'^#\s+(.+)$|<h1[^>]*>(.*?)</h1>|<title[^>]*>(.*?)</title>', text, re.M | re.I | re.S) if label.endswith('.html') else re.findall(r'^#\s+(.+)$', text, re.M)
    title = ' '.join(' '.join(t) if isinstance(t, tuple) else t for t in titles)
    if re.search(r'\bkiway\b', title, re.I):errors.append(f'{label}: stale KiWay title')
    for current, old in [('Quick SI', 'Signal Integrity Advisor'), ('Embed3D', 'Project Library')]:
        if current in name and old.lower() in title.lower():errors.append(f'{label}: stale {old} title; use {current}')
    return errors


def validate(root=ROOT, packages=True):
    root = Path(root); errors = []; inventory = sorted(root.glob('*_plugin/metadata.json'))
    if not inventory:return ['No active plugin metadata found']
    for path in [root/'README.md', root/'docs/USER_GUIDE.md', root/'docs/INSTALLATION.md', root/'docs/PI_REFERENCE_BENCHMARKS.md']:
        if not path.is_file():errors.append(f'{path}: missing document');continue
        errors += check_document(str(path), path.read_text(encoding='utf-8-sig'), lambda target, p=path: (p.parent/target).read_bytes())
    for metadata_path in inventory:
        folder = metadata_path.parent; metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig'))
        readmes = [p for p in folder.iterdir() if p.name.lower() == 'readme.md']
        docs = readmes + [folder/'help.html']
        if len(readmes) != 1:errors.append(f'{folder}: expected one README.md')
        if len(readmes)==1:
            for catalog in (root/'README.md',root/'docs/USER_GUIDE.md'):
                links,images=references(catalog.read_text(encoding='utf-8-sig'))
                targets={(catalog.parent/p).resolve() for url in links if (p:=local_path(url))}
                icons={(catalog.parent/p).resolve() for url in images if (p:=local_path(url))}
                if readmes[0].resolve() not in targets:errors.append(f'{catalog}: missing guide link for {folder.name}')
                if (folder/'icon.png').resolve() not in icons:errors.append(f'{catalog}: missing icon for {folder.name}')
        for path in docs:
            if not path.is_file():errors.append(f'{path}: missing document');continue
            errors += check_document(str(path), path.read_text(encoding='utf-8-sig'), lambda target, p=path: (p.parent/target).read_bytes(), require_image=True, name=metadata['name'])
        if not packages:continue
        feed_path = root/'pcm/pkgs.json'
        feed = json.loads(feed_path.read_text(encoding='utf-8-sig'))
        package = next((p for p in feed['packages'] if p['identifier'] == metadata['identifier']), None)
        if package is None:errors.append(f'{folder}: missing current PCM entry');continue
        for version in package['versions']:
            archive_path = root/'releases'/version['download_url'].rsplit('/',1)[-1]
            if not archive_path.is_file():errors.append(f'{archive_path}: missing package');continue
            with zipfile.ZipFile(archive_path) as archive:
                for path in docs:
                    entry = 'plugins/'+path.name
                    try:text = archive.read(entry).decode('utf-8-sig')
                    except KeyError:errors.append(f'{archive_path}:{entry}: missing document');continue
                    def read(target):
                        entry_target = posixpath.normpath(posixpath.join('plugins', target))
                        if entry_target.startswith('../') or entry_target.startswith('/'):raise ValueError('outside archive')
                        return archive.read(entry_target)
                    errors += check_document(f'{archive_path}:{entry}', text, read, require_image=True, check_links=False, name=metadata['name'])
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true', help='Check source docs before building ZIPs.')
    args = parser.parse_args()
    errors = validate(packages=not args.source_only)
    if errors:
        print('\n'.join(errors));return 1
    print('Current user documentation and local illustrations validated'+(' (source only).' if args.source_only else ', including PCM ZIP images.'));return 0


if __name__ == '__main__':raise SystemExit(main())
