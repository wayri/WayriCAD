"""IPC action launcher shared by the independently packaged tools."""
import ast
import importlib
import json
import os
from pathlib import Path
import sys
import traceback
import types


def _package_version(root):
    """Read the static version without running KiCad's legacy initializer."""
    try:
        tree = ast.parse((root / '__init__.py').read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == '__version__'
                                                for target in node.targets):
            try:
                version = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                return None
            return version if isinstance(version, str) else None
    return None


def _finish_loading_on_window(wx, loading, ready):
    """Dismiss the splash when a Run method enters a modal window's event loop."""
    active = [True]

    def finish():
        if not active[0]:
            return
        active[0] = False
        if ready and not Path(ready).is_file():
            Path(ready).touch()
        if loading:
            loading.finish()

    if not hasattr(wx, 'CallLater') or not hasattr(wx, 'GetTopLevelWindows'):
        finish()
        return finish
    previous = set(wx.GetTopLevelWindows())

    def check():
        if not active[0]:
            return
        if any(window not in previous and window.IsShown()
               for window in wx.GetTopLevelWindows()):
            finish()
        else:
            wx.CallLater(50, check)

    wx.CallLater(50, check)
    return finish


def main(root, action_class=None):
    root=Path(root).resolve()
    sys.path.insert(0,str(root))
    config={}
    loading=None
    try:
        config=json.loads((root/'wayricad-tool.json').read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict):
            raise ValueError('The installed plugin launch metadata must be a JSON object. Reinstall its ZIP package.')
        for field in ('tool','module','class','name'):
            if not isinstance(config.get(field),str) or not config[field]:
                raise ValueError('The installed plugin has invalid launch metadata: '+field+'. Reinstall its ZIP package.')
        from .bootstrap import relaunch
        from .loading import LoadingWindow
        ready = os.environ.get('WAYRICAD_SPLASH_READY')
        if not ready:
            loading = LoadingWindow(config['name'])
        profile={'planar_magnetics_plugin': 'magnetics',
                 'extract_pins_plugin': 'extract'}.get(config['tool'], 'ipc')
        status=relaunch(root, 'interboard_entrypoint.py' if action_class else 'ipc_entrypoint.py',
                        profile=profile, loading=loading)
        if status is not None:return status
        import wx
        from .loading import ensure_wx_app
        app=ensure_wx_app(wx)
        if config['tool']=='bom_studio_plugin':
            from bomstudio.launch import main as launch
            if ready:Path(ready).touch()
            if loading:loading.finish()
            return launch()
        if config['tool'] in {'trace_impedance_plugin', 'signal_integrity_advisor_plugin'}:
            from .native_analysis import launch
            if ready:Path(ready).touch()
            if loading:loading.finish()
            return launch(root, config['tool'])
        from .ipc import module
        sys.modules['pcbnew']=module()
        # IPC packages must not execute the legacy SWIG registration initializer.
        # A package namespace still permits relative imports in the tool modules.
        package='wayricad_active_plugin'
        module_obj=types.ModuleType(package)
        module_obj.__package__=package
        module_obj.__path__=[str(root)]
        version=_package_version(root)
        if version is not None:module_obj.__version__=version
        sys.modules[package]=module_obj
        if (root/'kilo').is_dir():sys.path.insert(0,str(root))
        target=importlib.import_module('.'+config['module'],package)
        plugin=getattr(target,action_class or config['class'])()
        finish_loading = _finish_loading_on_window(wx, loading, ready)
        plugin.Run()
        finish_loading()
        if wx.GetTopLevelWindows():app.MainLoop()
        return 0
    except Exception as exc:
        if loading:loading.finish()
        from .bootstrap import failure
        from .context import redact_error
        print(redact_error(traceback.format_exc()), file=sys.stderr)
        title=config.get('name','WayriCAD') if isinstance(config,dict) else 'WayriCAD'
        return failure(exc, title)
