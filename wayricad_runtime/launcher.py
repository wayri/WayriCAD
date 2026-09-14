"""IPC action launcher shared by the independently packaged tools."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback


def main(root):
    root=Path(root).resolve()
    sys.path.insert(0,str(root))
    config={}
    try:
        config=json.loads((root/'wayricad-tool.json').read_text(encoding='utf-8'))
        for field in ('tool','module','class','name'):
            if not isinstance(config.get(field),str) or not config[field]:
                raise ValueError('The installed plugin has invalid launch metadata: '+field+'. Reinstall its ZIP package.')
        import wx
        app=wx.App.Get() or wx.App(False)
        if config['tool']=='bom_studio_plugin':
            from bomstudio.launch import main as launch
            return launch()
        from .ipc import module
        sys.modules['pcbnew']=module()
        # The runtime namespace works both from a PCM install and a source checkout.
        package='wayricad_active_plugin'
        spec=importlib.util.spec_from_file_location(package,root/'__init__.py',submodule_search_locations=[str(root)])
        if spec is None or spec.loader is None:
            raise ValueError('The installed plugin is missing its Python entry point. Reinstall its ZIP package.')
        module_obj=importlib.util.module_from_spec(spec);sys.modules[package]=module_obj;spec.loader.exec_module(module_obj)
        if (root/'kilo').is_dir():sys.path.insert(0,str(root))
        target=importlib.import_module('.'+config['module'],package)
        plugin=getattr(target,config['class'])()
        plugin.Run()
        if wx.GetTopLevelWindows():app.MainLoop()
        return 0
    except Exception as exc:
        traceback.print_exc()
        try:
            import wx
            app=wx.App.Get() or wx.App(False)
            wx.MessageBox(str(exc)+'\n\nCheck Preferences > Plugins: enable the KiCad API and recreate this plugin environment if dependencies are missing.',
                          config.get('name','WayriCAD'),wx.OK|wx.ICON_ERROR)
        except Exception:
            print('WayriCAD could not create its local UI.',file=sys.stderr)
        return 1
