"""KiWay Bulk Label Editor plugin package."""

__version__ = "0.6.0"

from .bulk_label_editor_plugin import BulkLabelEditorPlugin

import wx

if wx.GetApp() is not None:
    BulkLabelEditorPlugin().register()

__all__ = ["BulkLabelEditorPlugin"]
