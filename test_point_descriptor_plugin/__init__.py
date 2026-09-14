"""WayriCAD Test Point Descriptor Extractor plugin entry point."""

try:
    from .test_point_descriptor_plugin import TestPointDescriptorPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    TestPointDescriptorPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        TestPointDescriptorPlugin().register()

__all__ = ["TestPointDescriptorPlugin"]
