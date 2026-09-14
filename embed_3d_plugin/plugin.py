"""KiCad ActionPlugin entry point. All writes occur inside Run's modal action."""
import pcbnew
import wx
from .logging_utils import get_logger
from .assets import toolbar_icon_path


class WayriCADEmbed3DPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'WayriCAD Embed3D — Design assets'
        self.category = 'Footprints / Portability'
        self.description = 'Embed, unbundle and relink footprints, 3D models and saved schematic symbols.'
        self.show_toolbar_button = True
        self.icon_file_name = toolbar_icon_path()
        self.dark_icon_file_name = toolbar_icon_path(dark=True)

    def Run(self):
        from .native import NativeBridge
        from .workspace_ui import WorkspaceDialog
        bridge, dialog, result = None, None, ''
        try:
            if getattr(pcbnew,'_wayricad_ipc',False):
                from .ipc_native import IPCBridge
                bridge=IPCBridge(pcbnew)
            else:
                bridge = NativeBridge(pcbnew)
            parent = wx.GetActiveWindow()
            dialog = WorkspaceDialog(parent, bridge)
            dialog.ShowModal()
            result = dialog.result_message
        except Exception as exc:
            log = get_logger()
            log.exception('Plugin could not run')
            wx.MessageBox(str(exc)+'\n\nDiagnostic log: '+log.log_path,
                          'WayriCAD Embed3D', wx.OK | wx.ICON_ERROR)
        finally:
            if dialog:
                dialog.Destroy()
            # Native RunActionPlugin must rebuild its view before releasing the
            # old footprint children. Do not call mutation code in CallAfter.
            leases = bridge.leases if bridge else []
            def after_action():
                leases.clear()
                if result:
                    wx.MessageBox(result, 'WayriCAD Embed3D · Complete', wx.OK | wx.ICON_INFORMATION)
            wx.CallAfter(after_action)
