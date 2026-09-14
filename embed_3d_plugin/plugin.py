"""KiCad ActionPlugin entry point. All writes occur inside Run's modal action."""
import pcbnew
import wx
from .logging_utils import get_logger
from .assets import toolbar_icon_path


class WayriCADEmbed3DPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'WayriCAD Project Library'
        self.category = 'Footprints / Portability'
        self.description = 'Create project-local footprint, symbol and 3D libraries with reviewed links and a backup.'
        self.show_toolbar_button = True
        self.icon_file_name = toolbar_icon_path()
        self.dark_icon_file_name = toolbar_icon_path(dark=True)

    def Run(self):
        from .native import NativeBridge
        from .project_ui import ProjectLibraryDialog
        bridge, dialog, result = None, None, ''
        try:
            if getattr(pcbnew,'_wayricad_ipc',False):
                from .ipc_native import IPCBridge
                bridge=IPCBridge(pcbnew)
            else:
                bridge = NativeBridge(pcbnew)
                from .project_launcher import launch
                board=bridge.board
                launch(str(board.GetFileName()) if board is not None else '')
                return  # independent window survives closing the source editor
            parent = wx.GetActiveWindow()
            dialog = ProjectLibraryDialog(parent, bridge)
            dialog.ShowModal()
            result = dialog.result_message
        except Exception as exc:
            log = get_logger()
            log.exception('Plugin could not run')
            wx.MessageBox(str(exc)+'\n\nDiagnostic log: '+log.log_path,
                          'WayriCAD Project Library', wx.OK | wx.ICON_ERROR)
        finally:
            if dialog:
                dialog.Destroy()
            # Native RunActionPlugin must rebuild its view before releasing the
            # old footprint children. Do not call mutation code in CallAfter.
            leases = bridge.leases if bridge else []
            def after_action():
                leases.clear()
                if result:
                    wx.MessageBox(result, 'WayriCAD Project Library · Complete', wx.OK | wx.ICON_INFORMATION)
            wx.CallAfter(after_action)


class WayriCADLiveAssetsPlugin(WayriCADEmbed3DPlugin):
    """Secondary native menu action retains tools that need the live editor."""
    def defaults(self):
        super().defaults()
        self.name='WayriCAD Advanced Live Assets'
        self.description='Advanced asset tools for the active PCB Editor board.'
        self.show_toolbar_button=False

    def Run(self):
        from .native import NativeBridge
        from .workspace_ui import WorkspaceDialog
        bridge=None;dialog=None
        try:
            if getattr(pcbnew,'_wayricad_ipc',False):
                raise RuntimeError('This action requires the native PCB Editor plugin context.')
            bridge=NativeBridge(pcbnew)
            if bridge.board is None:raise RuntimeError('Open a board in PCB Editor first.')
            dialog=WorkspaceDialog(wx.GetActiveWindow(),bridge)
            dialog.ShowModal()
        except Exception as exc:
            wx.MessageBox(str(exc),'WayriCAD Advanced Live Assets',wx.OK|wx.ICON_ERROR)
        finally:
            if dialog:dialog.Destroy()
            leases=bridge.leases if bridge else []
            wx.CallAfter(leases.clear)
