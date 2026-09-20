"""Verify saved rules in real KiCad DRC, without Studio running or user-board edits."""
import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cli',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--net-groups',action='store_true')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    helper=runpy.run_path(str(ROOT/'tests/test_layer_routing.py'))
    from protocol_constraint_composer_plugin.constraint_studio import routing_profiles as rp
    w=helper['fixture']()
    if args.net_groups:
        for old,new in [('D1','CAN1_P'),('D2','CAN1_N'),('D3','CAN2_P'),('D4','CAN2_N')]:
            w.board_text=w.board_text.replace('"'+old+'"','"'+new+'"')
        w.refresh_board_context()
        for i in (1,2):
            data=helper['profile'](w);data.update(name=f'CAN{i}',scope='nets',protocol='CAN',nets=[f'CAN{i}_P',f'CAN{i}_N'])
            if i==2:
                for r in data['rows']:r['width']*=1.2
            rp.install(w,data)
    else:rp.install(w,helper['profile'](w))
    s=w.board_text.replace('"D1"','"CAN_P"').replace('"D2"','"CAN_N"').rstrip()[:-1]
    for layer,y,width,separation in [('F.Cu',10,.2,.6),('B.Cu',15,.3,.8)]:
        for net,dy in [(1,0),(2,separation)]:
            s+=f'\n(segment (start 10 {y+dy}) (end 15 {y+dy}) (width {width}) (layer "{layer}") (net {net}) (uuid "{uuid.uuid4()}"))'
        s+=f'\n(segment (start 20 {y}) (end 25 {y}) (width 0.1) (layer "{layer}") (net 1) (uuid "{uuid.uuid4()}"))'
        if args.net_groups:
            s+=f'\n(segment (start 30 {y}) (end 35 {y}) (width 0.1) (layer "{layer}") (net 3) (uuid "{uuid.uuid4()}"))'
    w.board_text=s+'\n)\n'
    for ext,raw in w.outputs().items():(out/('routing'+ext)).write_bytes(raw)
    report=out/'native-drc.json'
    done=subprocess.run([args.cli,'pcb','drc','--format','json','--output',str(report),str(out/'routing.kicad_pcb')],capture_output=True,text=True,timeout=60)
    if done.returncode not in (0,5):raise RuntimeError(done.stdout+done.stderr)
    result=json.loads(report.read_text('utf-8'))
    descriptions=[v['description'] for v in result['violations']]
    checks={}
    for layer,minimum in [('F.Cu','0.1900'),('B.Cu','0.2850')]:
        instance='CAN1' if args.net_groups else 'CAN routing'
        checks[layer+' width']=any(f"{instance} / {layer}" in d and minimum in d for d in descriptions)
    if args.net_groups:
        for layer,minimum in [('F.Cu','0.2280'),('B.Cu','0.3420')]:
            checks[layer+' CAN2 isolation']=any(f'CAN2 / {layer}' in d and minimum in d for d in descriptions)
    for layer,maximum in [('F.Cu','0.1890'),('B.Cu','0.2625')]:
        checks[layer+' pair gap']=any('gap' in v['type'] and maximum in v['description'] and
            any(f'on {layer},' in item['description'] for item in v['items']) for v in result['violations'])
    summary=dict(status='passed' if all(checks.values()) else 'failed',checks=checks,
                 kicad_version=result.get('kicad_version'),violations=descriptions,
                 note='Deliberately violating disposable fixture; not a clean-board DRC claim or interactive routing UI test.')
    (out/'acceptance.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    return 0 if summary['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
