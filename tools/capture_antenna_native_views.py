"""Export real native 3D views from a saved result; never generate surrogate data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def capture(result_path, output):
    import wx
    from quick_emerge_plugin.ui import QuickEMergeFrame
    from quick_emerge_plugin.workspace_actions import result_views
    result = json.loads(result_path.read_bytes())
    app = wx.App.Get() or wx.App(False)
    frame = QuickEMergeFrame(Path(result['source']['path']))
    frame.SetSize((1600, 1100))
    frame.Show(); wx.Yield()
    output.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        frame._apply_setup_config(result['config'], result_path)
        frame.install_result(result)
        names=['3D setup'] + result_views(result, '3D')
        if result.get('s_parameters'): names.append('S-parameters')
        if 'Radiation pattern' in result_views(result,'2D'): names.append('Radiation pattern')
        for name in names:
            frame.select_view(name); wx.Yield()
            view = frame.viewports[name]
            view.refresh_canvas(); frame.Update(); wx.Yield()
            path = output / (name.lower().replace(' ', '-') + '.png')
            if hasattr(view, 'export_image'): view.export_image(str(path))
            else: view.figure.savefig(path, dpi=200)
            records.append({'file': path.name, 'view': name,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        if result.get('field', {}).get('e_real_v_m'):
            frame.field_quantity.SetStringSelection('E magnitude')
            frame.field_view.SetSelection(2)
            for phase in (0, 90):
                frame.field_phase.SetValue(phase); frame.refresh_field_views()
                frame.select_view('3D fields'); wx.Yield()
                view = frame.viewports['3D fields']
                path = output / f'3d-wave-phase-{phase}.png'
                view.refresh_canvas(); frame.Update(); wx.Yield()
                if hasattr(view, 'export_image'): view.export_image(str(path))
                else: view.figure.savefig(path, dpi=200)
                records.append({'file': path.name, 'view': '3D phase vectors', 'phase_deg': phase,
                                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        receipt = {'source_result_sha256': hashlib.sha256(result_path.read_bytes()).hexdigest(),
                   'captured_at_utc':datetime.now(timezone.utc).isoformat(),
                   'viewer_build':'unreleased source update based on 4.7.0',
                   'viewer_code_sha256':{name:hashlib.sha256((ROOT/'quick_emerge_plugin'/name).read_bytes()).hexdigest()
                                         for name in ('ui.py','scene_viewport.py','field_vectors.py','polarization_view.py')},
                   'config_sha256': result.get('config_sha256'),
                   'engine': result.get('analysis_engine', result.get('backend')),
                   'captures': records}
        (output / 'provenance.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    finally:
        frame.close(None); wx.Yield()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    capture(args.result, args.output)
