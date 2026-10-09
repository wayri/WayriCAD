"""Optional real-HTTP frontend regression; supply an existing jsdom installation.

Set BOM_STUDIO_JSDOM_PATH to its package directory. BOM_STUDIO_NODE optionally
selects Node; no browser packages are installed by the test or the plugin.
"""
import os
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
from bomstudio.server import Application, Server


class FrontendWorkflowTests(unittest.TestCase):
    def test_shipped_frontend_startup_edit_analytics_and_export(self):
        jsdom = os.environ.get('BOM_STUDIO_JSDOM_PATH')
        node = os.environ.get('BOM_STUDIO_NODE') or shutil.which('node')
        if not jsdom or not node:
            self.skipTest('Set BOM_STUDIO_JSDOM_PATH and provide Node for DOM/HTTP acceptance.')
        app = Application(demo=True)
        server = Server(app)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result = subprocess.run(
                [node, str(Path(__file__).with_name('frontend_workflow.cjs')), server.url],
                capture_output=True, text=True, encoding='utf-8', timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(5)
            shutil.rmtree(app.demo_directory)
