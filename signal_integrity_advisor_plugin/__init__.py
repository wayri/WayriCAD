from .signal_integrity_advisor_plugin import SignalIntegrityAdvisorPlugin

import wx

if wx.GetApp() is not None:
    SignalIntegrityAdvisorPlugin().register()
