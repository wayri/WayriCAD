"""Native package discovery and mixed-version installer failure contracts."""
import json
import sys
import zipfile
import pytest
from tools import install_suite


def test_swig_install_and_backup_without_ipc(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    folder = source / 'project_fusion_plugin'
    folder.mkdir(parents=True)
    metadata = {'identifier': 'org.wayri.projectfusion', 'name': 'Wayri Project Fusion',
                'versions': [{'version': '0.9.2', 'runtime': 'swig'}]}
    (folder / 'metadata.json').write_text(json.dumps(metadata))
    archives = tmp_path / 'archives'
    archives.mkdir()
    archive_path = archives / 'WayriCAD-project-fusion-0.9.2-PCM.zip'
    def archive(version='0.9.2'):
        package = dict(metadata, versions=[{'version': version, 'runtime': 'swig'}])
        with zipfile.ZipFile(archive_path, 'w') as z:
            z.writestr('metadata.json', json.dumps(package))
            z.writestr('plugins/__init__.py', '__version__="0.9.2"')
            z.writestr('plugins/action.py', '# Native action')
    archive()
    destination = tmp_path / 'KiCad/10.0/plugins'
    target = destination.parent / '3rdparty/plugins/org_wayri_projectfusion'
    monkeypatch.setattr(install_suite, 'ROOT', source)
    monkeypatch.setattr(sys, 'argv', ['install_suite', '--destination', str(destination),
                                   '--archive-dir', str(archives), '--apply'])
    install_suite.main()
    assert (target / 'action.py').is_file()
    assert not (target / 'plugin.json').exists()
    install_suite.main()
    assert len(list((destination.parent / 'wayricad-plugin-backups').iterdir())) == 1
    before = (target / 'action.py').read_bytes()
    archive('0.9.1')
    with pytest.raises(ValueError, match='source inventory'):
        install_suite.main()
    assert (target / 'action.py').read_bytes() == before
