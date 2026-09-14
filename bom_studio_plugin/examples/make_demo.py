"""Recreate synthetic demo fixtures. Not an electrically validated design."""
from pathlib import Path
import json
import uuid

ROOT=Path(__file__).parent
uid=lambda s:str(uuid.uuid5(uuid.NAMESPACE_URL,'wayricad-bom-demo/'+s))
q=lambda s:json.dumps(str(s),ensure_ascii=False)
root_id=uid('root');sheet_a=uid('sheetA');sheet_b=uid('sheetB')

LIB='''(lib_symbols
 (symbol "Demo:Part"
  (pin_names (offset 0.5)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" "X" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
  (property "Value" "Part" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
  (symbol "Part_0_1" (rectangle (start -2.54 2.54) (end 2.54 -2.54) (stroke (width 0) (type default)) (fill (type background))))
  (symbol "Part_1_1"
   (pin passive line (at -5.08 0 0) (length 2.54) (name "1" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
   (pin passive line (at 5.08 0 180) (length 2.54) (name "2" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
  )
 )
)'''

def variant(name,fields=None,flags=None):
    return '(variant (name '+q(name)+') '+ ' '.join('('+k+' '+('yes' if v else 'no')+')' for k,v in (flags or {}).items())+' '+''.join('(field (name '+q(k)+') (value '+q(v)+'))' for k,v in (fields or {}).items())+')'

def symbol(ref,value,mpn,price,fp='Resistor_SMD:R_0603_1608Metric',dnp=False,paths=None,variants_=None,x=50,y=50,fields=None):
    props={'Reference':ref,'Value':value,'Footprint':fp,'Datasheet':'','MPN':mpn,'Manufacturer':'DEMO Components',
           'Supplier':'DEMO Supplier — offline','SKU':'SKU-'+mpn,'UnitPrice':price,'Currency':'INR','Stock':'5000',
           'MOQ':'10','OrderMultiple':'10','LeadTime':'2','Lifecycle':'Active','PriceDate':'2026-09-09',
           'InternalPN':'DEMO-'+ref,'Assembly':'DNP' if dnp else 'FIT','Notes':'Synthetic demo part; revision ${REV}'}
    props.update(fields or {})
    s=f'(symbol (lib_id "Demo:Part") (at {x} {y} 0) (unit 1) (body_style 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (in_pos_files yes) (dnp {"yes" if dnp else "no"}) (uuid "{uid(ref)}")\n'
    for i,(k,v) in enumerate(props.items()):
        s+=f' (property {q(k)} {q(v)} (at {x} {y+4+i*1.5} 0)'+(' (hide yes)' if k not in ('Reference','Value') else '')+' (effects (font (size 1.27 1.27))))\n'
    for pin in ('1','2'):s+=f' (pin "{pin}" (uuid "{uid(ref+pin)}"))\n'
    s+=' (instances (project "BOM_Demo" '
    for path,instance_ref in paths or [('/'+root_id,ref)]:
        s+='(path '+q(path)+' (reference '+q(instance_ref)+') (unit 1) '+''.join(variants_ or [])+')'
    return s+'))\n)'


def sheet(name,suid,page,channel,dnp=False):
    variants_=variant('Economy',flags={'dnp':True}) if dnp else ''
    return f'''(sheet (at {50+page*30} 125) (size 25 15) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
 (stroke (width 0) (type default)) (fill (color 0 0 0 0)) (uuid "{suid}")
 (property "Sheetname" "{name}" (at {50+page*30} 123 0) (effects (font (size 1.27 1.27))))
 (property "Sheetfile" "Channel.kicad_sch" (at {50+page*30} 142 0) (effects (font (size 1.27 1.27))))
 (property "CHANNEL" "{channel}" (at 0 0 0) (hide yes))
 (instances (project "BOM_Demo" (path "/{root_id}" (page "{page}") {variants_})))
)'''


def main():
    parts=[]
    for i in range(1,5):
        vs=[variant('Economy',{'Assembly':'DNI'}, {'dnp':True})] if i==3 else []
        if i==4:vs=[variant('Qualification',{'Assembly':'FIT'},{'dnp':False})]
        parts.append(symbol('R'+str(i),'10k' if i<4 else '0R','DEMO-R0603-10K' if i<4 else 'DEMO-R0603-0R','1.20',dnp=i==4,variants_=vs,x=40+i*20,y=40))
    for i in range(1,4):
        vs=[variant('Economy',{'Assembly':'DNP'},{'dnp':True})] if i==3 else []
        parts.append(symbol('C'+str(i),'100n' if i<3 else '10u','DEMO-C0603-100N' if i<3 else 'DEMO-C0603-10U','2.50' if i<3 else '6.40',fp='Capacitor_SMD:C_0603_1608Metric',variants_=vs,x=40+i*20,y=70))
    parts.append(symbol('D1','LED Green','DEMO-LED-GREEN','4.50',fp='LED_SMD:LED_0603_1608Metric',x=60,y=100))
    parts.append(symbol('J1','Terminal 2P','DEMO-TERM-2P','24.00',fp='Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical',x=90,y=100))
    header=f'(kicad_sch (version 20260306) (generator "eeschema") (generator_version "10.0") (uuid "{root_id}") (paper "A4")\n'
    (ROOT/'BOM_Demo.kicad_sch').write_text(header+LIB+'\n'+'\n'.join(parts)+'\n'+sheet('Channel A',sheet_a,2,'A')+'\n'+sheet('Channel B',sheet_b,3,'B',True)+'\n (embedded_fonts no)\n)\n',encoding='utf-8')
    paths=[('/'+root_id+'/'+sheet_a,'R101'),('/'+root_id+'/'+sheet_b,'R201')]
    child=symbol('R101','1k','DEMO-R0603-1K','1.10',paths=paths,fields={'Notes':'Channel ${CHANNEL}; build ${BUILD_CODE}'})
    child_header=f'(kicad_sch (version 20260306) (generator "eeschema") (generator_version "10.0") (uuid "{uid("child")}") (paper "A4")\n'
    (ROOT/'Channel.kicad_sch').write_text(child_header+LIB+'\n'+child+'\n (embedded_fonts no)\n)\n',encoding='utf-8')
    pro={'meta':{'filename':'BOM_Demo.kicad_pro','version':1},'text_variables':{'REV':'A','BUILD_CODE':'DEMO-${REV}'},'schematic':{'top_level_sheets':[{'uuid':'00000000-0000-0000-0000-000000000000','name':'BOM_Demo','filename':'BOM_Demo.kicad_sch'}],'variants':[{'name':'Economy','description':'Lower-cost demo with fewer fitted parts'},{'name':'Qualification','description':'Includes the optional zero-ohm link'}],'bom_presets':[]}}
    (ROOT/'BOM_Demo.kicad_pro').write_text(json.dumps(pro,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
