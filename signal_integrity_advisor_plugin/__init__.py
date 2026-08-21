"""KiWay Signal Integrity Advisor plugin entry point."""

try:
    from .signal_integrity_advisor_plugin import SignalIntegrityAdvisorPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    SignalIntegrityAdvisorPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        SignalIntegrityAdvisorPlugin().register()

__all__ = ["SignalIntegrityAdvisorPlugin"]
