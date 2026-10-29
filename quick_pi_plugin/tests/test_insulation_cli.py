"""CLI screening preserves both its inputs and referenced source studies."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from quick_pi_plugin.cli import main
from quick_pi_plugin.tests.test_insulation_screen import batch,policy,measurement


def test_output_cannot_replace_referenced_study():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);study=root/'study.json';study.write_text('original source study')
        value=batch();value['request']={'study_input_path':str(study)}
        saved=root/'batch.json';saved.write_text(json.dumps(value))
        rules=policy();rules['reviewed_creepage']=[measurement()]
        rule_path=root/'rules.json';rule_path.write_text(json.dumps(rules))
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(['--insulation-result',str(saved),'--insulation-policy',str(rule_path),'--output',str(study)])==2
        assert study.read_text()=='original source study'
