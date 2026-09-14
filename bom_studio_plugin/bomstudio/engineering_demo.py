"""Prepare an explicitly fictional, temporary engineering sample. No accounts/keys supplied."""
from pathlib import Path
from datetime import datetime,timezone
import json
import shutil
from . import partsdb,engineering,qualification,variantlab,intelligence
from .footprints import symbol_pins
from .native import BASE

FOOTPRINT='''(footprint "R_0603_1608Metric" (version 20241229) (layer "F.Cu")
 (solder_mask_margin 0) (solder_paste_margin 0) (solder_paste_margin_ratio 0)
 (pad "1" smd rect (at -0.8 0) (size 0.9 1) (layers "F.Cu" "F.Paste" "F.Mask"))
 (pad "2" smd rect (at 0.8 0) (size 0.9 1) (layers "F.Cu" "F.Paste" "F.Mask")))
'''

def prepare(app):
    ws=app.workspace;root=ws.project.root.parent
    if not app.demo_directory or root!=Path(app.demo_directory).resolve():raise ValueError('Engineering sample must use a temporary demo copy.')
    fp=root/'demo-footprints/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod';fp.parent.mkdir(parents=True,exist_ok=True)
    models=root/'demo-models';models.mkdir(exist_ok=True)
    for model in (Path(__file__).resolve().parent.parent/'examples'/'assets').glob('SYNTHETIC_resistor.*'):shutil.copyfile(model,models/model.name)
    source=FOOTPRINT.rstrip()[:-1]+'\n(fp_rect (start -0.8 -0.4) (end 0.8 0.4) (layer "F.Fab") (stroke (width 0.1) (type default)))\n(fp_rect (start -1.45 -0.7) (end 1.45 0.7) (layer "F.CrtYd") (stroke (width 0.05) (type default)))\n(model "${KIPRJMOD}/demo-models/SYNTHETIC_resistor.wrl" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n(model "${KIPRJMOD}/demo-models/SYNTHETIC_resistor.step" (hide yes) (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n)'
    fp.write_text(source)
    intelligence.configure(ws,{'library_roots':[str(fp.parent.parent)]})
    rows=ws.rows()
    for row in rows:
        if row['ref'] in ('R1','C3'):ws.edit([row['id']],BASE,{'Mass':''})
    variantlab.apply(ws,variantlab.preview(ws,{'op':'create','name':'Quotation only','parent':BASE,'mode':'derived','description':'Independent BOM-only demonstration; not a native variant.','tags':['demo','quotation']}),'VARIANT')
    library=root/'DEMO_catalog';app.library_path=str(library);ws.commit('Attach fictional demo catalog',lambda:ws.state.setdefault('engineering',{}).update(library=str(library)));ws.save()
    with partsdb.Library(library,create=True) as lib:
        plan=partsdb.harvest([str(ws.project.pro_path)]);partsdb.import_harvest(lib,plan,'IMPORT','Synthetic demo initializer')
        for ref,stock,lifecycle in [('R1',25,'Active'),('C1',1000,'NRND')]:
            row=next(r for r in ws.rows() if r['ref']==ref);pid=partsdb.record_identity(row['fields'])
            record={'manufacturer':row['fields']['Manufacturer'],'mpn':row['fields']['MPN'],'supplier':'SYNTHETIC demonstration','sku':'NOT-ORDERABLE-'+ref,'stock':stock,'region':'IN','source_url':'https://example.invalid/SYNTHETIC-NOT-SUPPLIER-DATA','observed_at':datetime.now(timezone.utc).isoformat(),'reviewed':True,'lifecycle':lifecycle,'notes':'Fictional demonstration. Not a distributor observation.'}
            ep=engineering.evidence_preview(lib,pid,record);engineering.evidence_apply(lib,ep,'IMPORT','Synthetic demo initializer')
        row=next(r for r in ws.rows() if r['ref']=='R1');pins=symbol_pins(ws.project.by_id[row['id']])
        spec={'schema':'wayricad-land-pattern-1','manufacturer':row['fields']['Manufacturer'],'mpn':row['fields']['MPN'],'source_url':'https://example.invalid/SYNTHETIC-DRAWING','document_revision':'DEMO ONLY - NOT MANUFACTURER DATA','document_sha256':partsdb.digest(FOOTPRINT),'page':1,'reviewed_by':'Synthetic initializer','frame':'top-view-mm','tolerance_mm':.02,'angle_tolerance_deg':.1,'pads':[{k:v for k,v in pad.items() if k!='custom'} for pad in qualification.actual_geometry(fp)['pads']],'pin_functions':{k:[v] for k,v in pins['pin_names'].items()},'notes':'Schema and comparison demo only. Do not use this drawing as a qualified production land pattern.'}
        (root/'DEMO-land-pattern.json').write_text(json.dumps(spec,indent=2))
    app.startup_note='ENGINEERING DEMO: temporary files, fictional catalog/stock/lifecycle and a synthetic land pattern. No accounts created; no real supplier data.'
    return {'project':str(ws.project.pro_path),'library':str(library),'spec':str(root/'DEMO-land-pattern.json')}
