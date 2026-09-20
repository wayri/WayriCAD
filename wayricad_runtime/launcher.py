"""IPC action launcher shared by the independently packaged tools."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback


def main(root, action_class=None):
    root=Path(root).resolve()
    sys.path.insert(0,str(root))
    config={}
    try:
        config=json.loads((root/'wayricad-tool.json').read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict):
            raise ValueError('The installed plugin launch metadata must be a JSON object. Reinstall its ZIP package.')
        for field in ('tool','module','class','name'):
            if not isinstance(config.get(field),str) or not config[field]:
                raise ValueError('The installed plugin has invalid launch metadata: '+field+'. Reinstall its ZIP package.')
        from .bootstrap import relaunch
        profile='magnetics' if config['tool']=='planar_magnetics_plugin' else 'ipc'
        status=relaunch(root, 'interboard_entrypoint.py' if action_class else 'ipc_entrypoint.py', profile=profile)
        if status is not None:return status
        import wx
        app=wx.App.Get() or wx.App(False)
        if config['tool']=='bom_studio_plugin':
            from bomstudio.launch import main as launch
            return launch()
        if config['tool'] in {'trace_impedance_plugin', 'signal_integrity_advisor_plugin'}:
            from .native_analysis import launch
            return launch(root, config['tool'])
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
        plugin=getattr(target,action_class or config['class'])()
        plugin.Run()
        if wx.GetTopLevelWindows():app.MainLoop()
        return 0
    except Exception as exc:
        from .bootstrap import failure
        from .context import redact_error
        print(redact_error(traceback.format_exc()), file=sys.stderr)
        title=config.get('name','WayriCAD') if isinstance(config,dict) else 'WayriCAD'
        return failure(exc, title)
