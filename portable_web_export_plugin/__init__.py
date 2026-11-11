"""WayriCAD Portable Web Export package."""

__version__ = "4.8.1"

PortableWebExportPlugin = None
try:
    import pcbnew  # noqa: F401
    import wx
except ImportError:
    pass
else:
    from .portable_web_export_plugin import PortableWebExportPlugin

    if wx.GetApp() is not None:
        PortableWebExportPlugin().register()

__all__ = ["PortableWebExportPlugin", "__version__"]
