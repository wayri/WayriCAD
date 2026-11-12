"""Native controller contract without opening a window or touching user designs."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Requires native wxPython')
class PreviewGateTests(unittest.TestCase):
    def setUp(self):
        from portable_web_export_plugin.exporter import scan_project
        self.temp = tempfile.TemporaryDirectory(prefix='portable-preview-')
        self.root = Path(self.temp.name)
        self.board = self.root/'sample.kicad_pcb'
        self.board.write_text('(kicad_pcb (uuid 11111111-1111-1111-1111-111111111111))')
        self.output = self.root/'review.html'
        self.document = '<!doctype html>\r\nExact reviewed document\n'
        self.controller = SimpleNamespace(scan=scan_project(self.board), preview_current=True,
            preview_document=self.document, preview_manifest={'revisionId':'reviewed-revision'},
            destination=Mock(GetPath=Mock(return_value=str(self.output))),
            export_button=Mock(), status=Mock(), _refresh_preflight=Mock())

    def tearDown(self):
        self.temp.cleanup()

    def test_changed_source_blocks_native_export_without_rebuilding(self):
        from portable_web_export_plugin.ui import PortableWebExportFrame
        self.board.write_bytes(self.board.read_bytes()+b'\n')
        with patch('portable_web_export_plugin.ui.wx.YieldIfNeeded'), patch(
                'portable_web_export_plugin.ui.wx.MessageBox') as message, patch(
                'portable_web_export_plugin.ui.write_export_document') as writer:
            PortableWebExportFrame._export(self.controller,None)
            writer.assert_not_called()
            message.assert_called_once()
            self.assertIn('changed since scan',message.call_args.args[0])
        self.assertFalse(self.output.exists())

    def test_native_export_writes_exact_reviewed_bytes_and_preserves_source(self):
        from portable_web_export_plugin.ui import PortableWebExportFrame
        original = self.board.read_bytes()
        dialog = Mock(ShowModal=Mock(return_value=wx.ID_NO))
        with patch('portable_web_export_plugin.ui.wx.YieldIfNeeded'), patch(
                'portable_web_export_plugin.ui.wx.MessageDialog',return_value=dialog):
            PortableWebExportFrame._export(self.controller,None)
        self.assertEqual(self.output.read_bytes(),self.document.encode('utf-8'))
        self.assertEqual(self.board.read_bytes(),original)
