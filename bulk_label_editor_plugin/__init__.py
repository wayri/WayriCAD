"""KiWay Bulk Label Editor plugin package."""

__version__ = "0.7.1"

try:
    from .bulk_label_editor_plugin import BulkLabelEditorPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    BulkLabelEditorPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        BulkLabelEditorPlugin().register()

__all__ = ["BulkLabelEditorPlugin"]
