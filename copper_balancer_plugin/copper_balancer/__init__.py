"""KiCad discovers this package in its scripting/plugins directory."""

__version__ = "3.1.0"

try:
    import pcbnew
except ImportError:
    pcbnew = None

if pcbnew is not None:
    import os
    import wx
    # pcbnew is also usable by headless scripts; registration requires the host.
    if wx.GetApp() is not None and not os.environ.get("WAYRICAD_COPPER_NO_REGISTER"):
        from .plugin import CopperBalancerPlugin
        CopperBalancerPlugin().register()
