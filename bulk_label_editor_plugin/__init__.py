"""KiWay Bulk Label Editor plugin package."""

__version__ = "0.5.0"

from .bulk_label_editor_plugin import BulkLabelEditorPlugin

BulkLabelEditorPlugin().register()

__all__ = ["BulkLabelEditorPlugin"]
