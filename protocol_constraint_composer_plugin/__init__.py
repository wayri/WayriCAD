"""KiWay Protocol Constraint Composer plugin entry point."""

try:
    from .protocol_constraint_composer_plugin import ProtocolConstraintComposerPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    ProtocolConstraintComposerPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        ProtocolConstraintComposerPlugin().register()

__all__ = ["ProtocolConstraintComposerPlugin"]
