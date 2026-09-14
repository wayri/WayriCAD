"""WayriCAD Embed3D: actual embedded model files, unchanged model transforms."""
__version__ = '3.0.0'


def register():
    global _plugin
    from .plugin import WayriCADEmbed3DPlugin
    _plugin = WayriCADEmbed3DPlugin()
    _plugin.register()
    return _plugin


# Core and CLI imports remain usable without KiCad/wxPython.
import os as _os
import sys as _sys
if 'pcbnew' in _sys.modules and _os.environ.get('WAYRICAD_EMBED3D_NO_REGISTER') != '1':
    try:
        register()
    except Exception:
        from .logging_utils import get_logger as _get_logger
        _get_logger().exception('Plugin registration failed')
