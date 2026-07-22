"""KiWay Connector ICD Builder plugin entry point."""

from .connector_icd_plugin import ConnectorICDPlugin

import wx

if wx.GetApp() is not None:
    ConnectorICDPlugin().register()

