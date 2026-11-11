"""Catch runtime/PCM version drift before independent plugin suites run."""
import ast
import json
from pathlib import Path


def test_declared_plugin_runtime_versions_match_metadata():
    root=Path(__file__).resolve().parents[1]
    checked=[]
    for metadata_path in sorted(root.glob('*_plugin/metadata.json')):
        expected=json.loads(metadata_path.read_text(encoding='utf-8'))['versions'][0]['version']
        for relative in ('__init__.py','bomstudio/__init__.py','copper_balancer/__init__.py',
                         'src/wayricad_mechanical/__init__.py'):
            initializer=metadata_path.parent/relative
            if not initializer.is_file():continue
            values=[node.value.value for node in ast.parse(initializer.read_bytes()).body
                    if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant)
                    and any(isinstance(target,ast.Name) and target.id=='__version__' for target in node.targets)]
            if values:
                assert values==[expected],str(initializer)
                checked.append(initializer)
        standalone=metadata_path.parent/'tools/pcm-package.json'
        if standalone.is_file():
            assert json.loads(standalone.read_text(encoding='utf-8'))['versions'][0]['version']==expected,str(standalone)
    assert checked,'No declared plugin runtime versions were checked.'
