"""Capture actual native source-geometry previews, explicitly without solved fields."""
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    import wx
    from quick_emerge_plugin.ui import QuickEMergeFrame
    app=wx.App(False)
    for template in ('cheh-lin-2023-siw-dra','ma-2024-siw-horn'):
        setup=ROOT/'examples/quick_emerge/research_antennas'/ (template+'.json')
        config=json.loads(setup.read_bytes())['config']
        output=ROOT/'examples/quick_emerge/research_antennas/images/paper-vnext'/template
        output.mkdir(parents=True,exist_ok=True)
        frame=QuickEMergeFrame(ROOT/'quick_emerge_plugin/tests/fixtures/region_coupon.kicad_pcb')
        frame.SetSize((1600,1100)); frame.Show(); wx.Yield()
        try:
            frame._apply_setup_config(config,setup); frame.preview(None)
            frame.select_view('3D setup'); wx.Yield()
            view=frame.viewports['3D setup']; view.refresh_canvas(); frame.Update(); wx.Yield()
            image=output/'geometry.png'; view.export_image(str(image))
            from quick_emerge_plugin.paper_scene import descriptor
            receipt={'kind':'native geometry preview; no FEM field or radiation result',
                     'captured_at_utc':datetime.now(timezone.utc).isoformat(),
                     'setup_sha256':hashlib.sha256(setup.read_bytes()).hexdigest(),
                     'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                     'assumptions':descriptor(config).get('assumptions',[]),
                     'scene':descriptor(config)}
            # arguments can be the config in setup views, never substitute solved data.
            (output/'geometry-provenance.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        finally:
            frame.close(None); wx.Yield()


if __name__=='__main__': main()
