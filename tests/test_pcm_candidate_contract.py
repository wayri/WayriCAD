"""Build every independent PCM archive and exercise its KiCad 10 menu scan."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from build_pcm import create_plugin_zip, normalize_metadata
from tools import validate_packages


ROOT = Path(__file__).resolve().parents[1]

SCAN = r'''
import importlib.util,json,pathlib,sys,types
root=pathlib.Path(sys.argv[1])
actions=[]
class ActionPlugin:
    def register(self):
        self.defaults()
        actions.append(self.name)
pcbnew=types.ModuleType('pcbnew')
pcbnew.ActionPlugin=ActionPlugin
wx=types.ModuleType('wx')
wx.GetApp=lambda:object()
sys.modules.update(pcbnew=pcbnew,wx=wx)
spec=importlib.util.spec_from_file_location('isolated_pcm',root/'__init__.py',submodule_search_locations=[str(root)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
loaded=[name for name in sys.modules if name.startswith('isolated_pcm.')]
pathlib.Path(sys.argv[2]).write_text(json.dumps({'actions':actions,'version':package.__version__,
                                                 'eager_tool_modules':loaded}),encoding='utf-8')
'''


def test_all_current_pcm_packages_validate_and_register_independently(tmp_path):
    plugin_paths=sorted(ROOT.glob('*_plugin/metadata.json'))
    assert len(plugin_paths)==16
    output=tmp_path/'archives'
    for metadata_path in plugin_paths:
        plugin=metadata_path.parent
        metadata=normalize_metadata(json.loads(metadata_path.read_text(encoding='utf-8')),
                                    plugin,'develop')
        with contextlib.redirect_stdout(io.StringIO()):
            create_plugin_zip(plugin,metadata['versions'][0]['version'],output,metadata)
    with contextlib.redirect_stdout(io.StringIO()):
        validate_packages.validate_candidate_archives(output)
    for archive_path in sorted(output.glob('*.zip')):
        stage=tmp_path/archive_path.stem
        with zipfile.ZipFile(archive_path) as archive:
            manifest=json.loads(archive.read('plugins/plugin.json'))
            version=json.loads(archive.read('metadata.json'))['versions'][0]['version']
            for member in archive.namelist():
                if member.startswith('plugins/'):
                    archive.extract(member,stage)
        result_path=stage/'scan.json'
        result=subprocess.run([sys.executable,'-I','-c',SCAN,str(stage/'plugins'),str(result_path)],
                              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,timeout=15)
        assert result.returncode==0, archive_path.name
        observed=json.loads(result_path.read_text(encoding='utf-8'))
        assert manifest['actions'][0]['name'] in observed['actions']
        assert observed['version']==version
        assert not observed['eager_tool_modules'], archive_path.name
