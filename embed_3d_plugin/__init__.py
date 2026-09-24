"""WayriCAD Embed3D: actual embedded model files, unchanged model transforms."""
__version__ = '3.4.0'


def register():
    global _plugin, _live_plugin
    from .plugin import WayriCADEmbed3DPlugin, WayriCADLiveAssetsPlugin
    _plugin = WayriCADEmbed3DPlugin()
    _plugin.register()
    if not getattr(_sys.modules.get('pcbnew'),'_wayricad_ipc',False):
        _live_plugin=WayriCADLiveAssetsPlugin()
        _live_plugin.register()
    return _plugin


# Core and CLI imports remain usable without KiCad/wxPython.
import os as _os
import sys as _sys
if 'pcbnew' in _sys.modules and _os.environ.get('WAYRICAD_EMBED3D_NO_REGISTER') != '1':
    try:
        import wx as _wx
        if _wx.GetApp() is not None:
            register()
    except Exception:
        from .logging_utils import get_logger as _get_logger
        _get_logger().exception('Plugin registration failed')
