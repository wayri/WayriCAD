"""Trusted tiny import fixtures and analytical candidate-runtime gates.

Fixture generation uses only the standard library. These synthetic examples
exercise parser/adapter execution, not electromagnetic convergence or production
manufacturing coverage. All generated paths belong to the qualification run.
"""
from pathlib import Path
import json
import struct
import tempfile

def _real8(value):
    if value==0:return bytes(8)
    sign=0x80 if value<0 else 0;value=abs(value);exponent=64
    while value>=1:value/=16;exponent+=1
    while value<1/16:value*=16;exponent-=1
    return bytes([sign|exponent])+int(value*(1<<56)).to_bytes(7,'big')

def gds_fixture(path):
    def rec(kind,dtype,payload=b''):
        if len(payload)%2:payload+=b'\0'
        return struct.pack('>HBB',len(payload)+4,kind,dtype)+payload
    data=rec(0,2,struct.pack('>h',600))+rec(1,2,struct.pack('>12h',*([2026,1,1,0,0,0]*2)))
    data+=rec(2,6,b'REPORT_IMPORT_FIXTURE')+rec(3,5,_real8(.001)+_real8(1e-6))
    data+=rec(5,2,struct.pack('>12h',*([2026,1,1,0,0,0]*2)))+rec(6,6,b'TOP')
    data+=rec(8,0)+rec(13,2,struct.pack('>h',1))+rec(14,2,struct.pack('>h',0))
    data+=rec(16,3,struct.pack('>10i',0,0,1000,0,1000,1000,0,1000,0,0))+rec(17,0)+rec(7,0)+rec(4,0)
    path.write_bytes(data)

def gds_recipe():
    return {'schema':1,'reviewed':True,'units':'embedded','gds_db_unit_m':1e-6,
            'materials':{'PEC':{'type':'pec'}},'layers':[{'layer':1,'datatype':0,'name':'Metal','z_m':0,'thickness_m':.0002,'material':'PEC'}]}

def gerber_fixture(root):
    root.mkdir(parents=True,exist_ok=True)
    text='%FSLAX46Y46*%\n%MOMM*%\n%LPD*%\n%ADD10C,0.600*%\nD10*\nX01000000Y01000000D03*\nM02*\n'
    for name in ('top.gbr','bottom.gbr'):(root/name).write_text(text,encoding='ascii')
    (root/'holes.drl').write_text('M48\n;FILE_FORMAT=3:3\nMETRIC,TZ\nT1C0.200\n%\nT1\nX1.000Y1.000\nM30\n',encoding='ascii')
    return {'schema':1,'reviewed':True,'units':'mm','materials':{'FR4':{'type':'dielectric','er':4.2},'Cu':{'type':'pec'}},
            'copper_layers':[{'file':'bottom.gbr','index':0,'name':'Bottom'},{'file':'top.gbr','index':1,'name':'Top'}],
            'substrate':{'thickness_mm':1,'material':'FR4','outline_mm':[[0,0],[2,0],[2,2],[0,2]]},
            'trace_material':'Cu','trace_thickness_um':35,'drills':[{'file':'holes.drl','plated':True}]}

def xml_fixture(root):
    text='<Stackup schemaVersion="3.1"><Materials><Material Name="FR4" Type="Dielectric" Permittivity="4.2" DielectricLossTangent="0.02"/></Materials><ELayers LengthUnit="mm"><Dielectrics><Dielectric Name="Substrate" Material="FR4" Zmin="-1" Zmax="0"/></Dielectrics><Layers><Layer Name="M1" Type="conductor" Material="PEC" Layer="1" Zmin="0" Zmax="0.2"/></Layers></ELayers></Stackup>'
    (root/'stack.xml').write_text(text,encoding='utf-8')
    return {'schema':1,'reviewed':True,'units':'embedded','xml_file':'stack.xml','layer_names':['M1'],'material_names':['FR4','AIR'],'gds_db_unit_m':1e-6}

def odb_fixture(root):
    (root/'matrix').mkdir(parents=True,exist_ok=True)
    matrix='STEP {\nCOL=1\nNAME=board\nID=1\n}\n'
    for row,name,kind in [(1,'top','SIGNAL'),(2,'core','DIELECTRIC'),(3,'bottom','SIGNAL')]:
        matrix+='LAYER {\nROW='+str(row)+'\nCONTEXT=BOARD\nTYPE='+kind+'\nNAME='+name+'\nPOLARITY=POSITIVE\nID='+str(row)+'\n}\n'
    (root/'matrix/matrix').write_text(matrix,encoding='ascii')
    step=root/'steps/board';step.mkdir(parents=True,exist_ok=True)
    def square(x0,y0,x1,y1):return 'UNITS=MM\nS P 0\nOB '+str(x0)+' '+str(y0)+' I\nOS '+str(x1)+' '+str(y0)+'\nOS '+str(x1)+' '+str(y1)+'\nOS '+str(x0)+' '+str(y1)+'\nOS '+str(x0)+' '+str(y0)+'\nOE\nSE\n'
    (step/'profile').write_text(square(0,0,2,2),encoding='ascii')
    for name in ('top','bottom'):
        layer=step/'layers'/name;layer.mkdir(parents=True,exist_ok=True)
        (layer/'features').write_text(square(.3,.3,1.7,1.7),encoding='ascii')
    return {'schema':1,'reviewed':True,'units':'embedded','materials':{'FR4':{'type':'dielectric','er':4.2},'Cu':{'type':'pec'}},'substrate_material':'FR4','trace_material':'Cu','stack_thickness_m':[.000035,.001,.000035],'layer_names':['top','bottom'],'reverse_stack':False,'generate_vias':False}

def import_smoke_configs(directory,base):
    """Yield the four reviewed tiny fabrication-import scattering cases."""
    from copy import deepcopy
    from .advanced_imports import import_identity
    from .model import validate_config
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='import-qualification-',dir=directory))
    for kind in ('gds','gds_xml','gerber','odb'):
        folder=root/kind;folder.mkdir()
        if kind in ('gds','gds_xml'):
            source=folder/'square.gds';gds_fixture(source)
            recipe=gds_recipe() if kind=='gds' else xml_fixture(folder)
        else:
            source=folder/'source'
            recipe=gerber_fixture(source) if kind=='gerber' else odb_fixture(source)
        recipe_path=folder/'review.json'
        recipe_path.write_text(json.dumps(recipe,indent=2),encoding='utf-8')
        identity=import_identity(kind,source,recipe_path)
        config=deepcopy(base)
        config.update(points=2,field_grid=3,mesh_edge_mm=.4)
        config['advanced']=dict(config.get('advanced',{}),study='scattering',step_path='',step_sha256='',
                                import_kind=kind,import_path=str(source.resolve()),
                                import_recipe_path=str(recipe_path.resolve()),import_sha256=identity['sha256'],
                                export_dxf=False,export_optycal=False)
        yield 'import_'+kind,validate_config(config)


def qualification_source_board(directory):
    """Create an empty PCB custody fixture; it supplies no simulated geometry."""
    from .model import source_identity
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/'qualification-context.kicad_pcb'
    data=b'(kicad_pcb (version 20241229) (generator "wayricad-qualification") (general (thickness 1.6)) (paper "A4") (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (setup (pad_to_mask_clearance 0)))\n'
    if target.exists() and target.read_bytes()!=data:raise ValueError('Qualification source fixture path contains different data')
    target.write_bytes(data)
    return source_identity(target)


def qualify_network_api():
    """Require actual upstream AAA fitting and exact sampled component results."""
    import numpy as np
    from .network import SampledNetwork
    from .network_extensions import rational_fit,deserialize_network,embed_components,touchstone_text
    frequencies=np.linspace(1e8,1e9,17);delay=1e-10
    samples=np.zeros((17,2,2),complex)
    samples[:,0,1]=samples[:,1,0]=np.exp(-2j*np.pi*frequencies*delay)
    dense=np.linspace(frequencies[0],frequencies[-1],101)
    fitted=rational_fit(SampledNetwork(frequencies,samples),dense,method='aaa',tolerance=1e-7)
    network=deserialize_network(fitted['derived_network'])
    if np.max(np.abs(network.s[:,1,0]-np.exp(-2j*np.pi*dense*delay)))>2e-8 or fitted['fit']['sample_max_abs_error']>1e-7 or fitted['fit']['holdout_max_abs_error'] is None or fitted['fit']['holdout_max_abs_error']>1e-7:raise ValueError('Actual EMerge AAA fit does not match the independent analytical delay reference')
    matched=SampledNetwork([1e9],[[[0]]])
    loaded=embed_components(matched,[dict(connection='shunt',element='R',value_si=50,unit='ohm',ports=[0])])
    if abs(loaded.s[0,0,0]+1/3)>1e-12:raise ValueError('Sampled component stamping disagrees with the parallel-resistor reference')
    asymmetric=SampledNetwork([1e9],[[[.1,.2],[.3,.4]]])
    lines=[line for line in touchstone_text(asymmetric).splitlines() if not line.startswith(('!','#'))]
    values=list(map(float,lines[0].split()))
    if values[1::2]!=[.1,.3,.2,.4]:raise ValueError('Touchstone two-port direction ordering check failed')
    return 'network_aaa_fit_rlc_touchstone_reference'
