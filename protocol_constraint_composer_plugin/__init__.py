from .protocol_constraint_composer_plugin import ProtocolConstraintComposerPlugin
try:
    import wx
    if wx.GetApp() is not None:ProtocolConstraintComposerPlugin().register()
except Exception:pass
