"""Process-isolated local wx WebViews for out-of-process KiCad plugins.

WebView2's default python.exe profile collides across plugin processes. Keep
one private profile for the lifetime of each process, shared by its views:
Edge creates its child environment asynchronously after WebView.New returns.
"""
from __future__ import annotations
import atexit
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

_profile = None
_profile_pid = None
_lock = threading.Lock()


def prepare_profile():
    """Select a writable, private per-process WebView2 data directory."""
    global _profile, _profile_pid
    if sys.platform != 'win32':
        return None
    with _lock:
        if _profile is None or _profile_pid != os.getpid():
            _profile = tempfile.mkdtemp(prefix='wayricad-webview-')
            _profile_pid = os.getpid()
            directory = _profile
            atexit.register(lambda: shutil.rmtree(directory, ignore_errors=True))
        # Do not restore early: WebView2 reads this during async creation.
        os.environ['WEBVIEW2_USER_DATA_FOLDER'] = _profile
        return Path(_profile)


def new_webview(parent, **kwargs):
    """Create a native view without sharing another plugin process's profile."""
    prepare_profile()
    import wx.html2 as html2
    backend = kwargs.pop('backend', html2.WebViewBackendEdge if sys.platform == 'win32' else html2.WebViewBackendDefault)
    if not html2.WebView.IsBackendAvailable(backend):
        raise RuntimeError('The native browser runtime is unavailable. On Windows install Microsoft Edge WebView2 Runtime.')
    return html2.WebView.New(parent, backend=backend, **kwargs)


def try_new_webview(parent, **kwargs):
    """Return (view, reason) so optional previews cannot disable core tools."""
    try:
        return new_webview(parent, **kwargs), ''
    except Exception as exc:
        advice = ('Install Microsoft Edge WebView2 Runtime.' if sys.platform == 'win32'
                  else 'Install your system wxPython WebKit browser runtime.')
        return None, 'Native visual preview unavailable. '+advice+' Tables and exports remain available. '+str(exc)
