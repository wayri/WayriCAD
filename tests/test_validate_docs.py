import json
from io import BytesIO
import zipfile

from tools.validate_docs import check_document, validate
from PIL import Image


buffer = BytesIO()
Image.new('RGB', (2, 2)).save(buffer, format='PNG')
PNG = buffer.getvalue()


def test_missing_broken_and_invalid_images_are_actionable():
    assert 'illustration' in check_document('README.md', '# Tool', lambda _: b'', require_image=True)[0]
    def missing(_):raise FileNotFoundError()
    assert 'missing local target' in check_document('README.md', '![view](missing.png)', missing)[0]
    assert 'invalid' in check_document('help.html', '<img src="bad.png">', lambda _: b'not a png')[0]


def test_titles_and_remote_links_do_not_hide_missing_local_help():
    errors = check_document('help.html', '<title>WayriCAD Signal Integrity Advisor</title><img src="https://example.com/view.png">', lambda _: b'', require_image=True, name='WayriCAD Quick SI')
    assert len(errors) == 2
    assert check_document('README.md', '# Embed3D\nPreviously Project Library.\n![view](view.png)\n[external](https://example.com)', lambda _: PNG, require_image=True, name='WayriCAD Embed3D') == []


def test_inventory_and_zip_image_validation(tmp_path):
    folder = tmp_path/'one_plugin';folder.mkdir()
    (tmp_path/'docs').mkdir();(tmp_path/'pcm').mkdir();(tmp_path/'releases').mkdir()
    (tmp_path/'README.md').write_text('[guide](docs/USER_GUIDE.md)')
    (tmp_path/'docs/USER_GUIDE.md').write_text('# Guide')
    metadata = {'identifier': 'example.one', 'name': 'WayriCAD One'}
    (folder/'metadata.json').write_text(json.dumps(metadata))
    readme = '# WayriCAD One\n![view](screen.png)\n[guide](../docs/USER_GUIDE.md)'
    help_text = '<h1>WayriCAD One</h1><img src="screen.png">'
    (folder/'README.md').write_text(readme);(folder/'help.html').write_text(help_text);(folder/'screen.png').write_bytes(PNG)
    (tmp_path/'pcm/pkgs.json').write_text(json.dumps({'packages':[dict(metadata,versions=[{'download_url':'https://example.com/one.zip'}])]}))
    archive = tmp_path/'releases/one.zip'
    with zipfile.ZipFile(archive,'w') as out:
        out.writestr('plugins/README.md',readme);out.writestr('plugins/help.html',help_text)
    errors = validate(tmp_path)
    assert len(errors) == 2 and all('screen.png' in e for e in errors)
    with zipfile.ZipFile(archive,'a') as out:out.writestr('plugins/screen.png',PNG)
    assert validate(tmp_path) == []
    (tmp_path/'retired_plugin').mkdir()
    (tmp_path/'retired_plugin/metadata.legacy.json').write_text('{}')
    assert validate(tmp_path,packages=False) == []
