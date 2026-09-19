"""Private browser profile lifetime across real plugin processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from wayricad_runtime import local_webview

ROOT = Path(__file__).resolve().parents[1]


class WebViewProfileTests(unittest.TestCase):
    def test_optional_preview_failure_preserves_actionable_fallback(self):
        with patch.object(local_webview, 'new_webview', side_effect=RuntimeError('backend missing')):
            view, reason = local_webview.try_new_webview(None)
        self.assertIsNone(view)
        self.assertIn('Tables and exports remain available', reason)
        self.assertIn('backend missing', reason)

    def test_profile_reused_until_process_exit_and_ambient_profile_ignored(self):
        with patch.object(local_webview.sys, 'platform', 'win32'), patch.dict(os.environ, {'WEBVIEW2_USER_DATA_FOLDER':'not-our-profile'}):
            first = local_webview.prepare_profile()
            second = local_webview.prepare_profile()
            self.assertEqual(first, second)
            self.assertTrue(first.is_dir())
            self.assertEqual(os.environ['WEBVIEW2_USER_DATA_FOLDER'], str(first))
            (first / 'writable-test').write_text('local', encoding='utf-8')

    @unittest.skipUnless(sys.platform == 'win32', 'WebView2 profile isolation is Windows-specific')
    def test_distinct_processes_never_share_profile(self):
        code = "import sys,json;sys.path.insert(0,sys.argv[1]);from wayricad_runtime.local_webview import prepare_profile;print(json.dumps(str(prepare_profile())))"
        paths = [json.loads(subprocess.check_output([sys.executable, '-I', '-c', code, str(ROOT)], text=True, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)) for _ in range(2)]
        self.assertNotEqual(*paths)
        # atexit removes unlocked profile directories for clean lifetimes.
        self.assertTrue(all(not Path(path).exists() for path in paths))

