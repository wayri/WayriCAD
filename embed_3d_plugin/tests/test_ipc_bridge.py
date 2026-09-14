"""IPC saved-file capability and CLI acceptance contracts; no editor mutation."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from embed_3d_plugin.ipc_native import IPCBridge


class IPCBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge=IPCBridge(SimpleNamespace(GetBoard=lambda:None,Version=lambda:'11.0.0'))

    def test_native_features_are_explicitly_unavailable(self):
        self.assertFalse(self.bridge.supports_normalization)
        self.assertFalse(self.bridge.supports_live_tools)
        with self.assertRaisesRegex(RuntimeError,'normalization'):
            self.bridge.extract_normalized_footprints('board')
        with self.assertRaisesRegex(RuntimeError,'unavailable'):
            self.bridge.deserialize('(footprint "A")')

    def test_cli_success_requires_a_real_export_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory,'part.kicad_mod');source.write_text('(footprint "part")')
            with patch('embed_3d_plugin.ipc_native.find_cli',return_value=Path('kicad-cli')),patch('embed_3d_plugin.ipc_native.subprocess.run') as run:
                run.return_value=SimpleNamespace(returncode=0,stdout='',stderr='')
                with self.assertRaisesRegex(ValueError,'validation failed'):
                    self.bridge.validate_footprint_file(source)
                def export(command,**kwargs):
                    self.assertEqual(command[1:4],['fp','export','svg'])
                    output=Path(command[command.index('--output')+1]);(output/'part.svg').write_text('<svg/>')
                    return SimpleNamespace(returncode=0,stdout='',stderr='')
                run.side_effect=export
                self.bridge.validate_footprint_file(source)


if __name__=='__main__':unittest.main()
