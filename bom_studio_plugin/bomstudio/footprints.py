"""Read-only physical evidence from local footprints, PCB and embedded symbols.

Name interpretation is heuristic, never a qualified land-pattern comparison.
Numbered pads are counted uniquely; paste apertures, holes and thermal-via
replicas do not inflate electrical pad count. No board/library is modified.
"""
from __future__ import annotations
import hashlib
import math
import os
from pathlib import Path
import re
from .sexpr import parse, properties
from .native import natural


def package_hint(text):
    s=str(text or '').rsplit(':',1)[-1].upper().replace('µ','U')
    result={'raw':str(text or ''),'family':None,'pin_count':None,'pitch_mm':None,'body_mm':None,'exposed_pad':None}
    passive=re.search(r'(\d{4})[_ (]+(\d{4})\s*METRIC',s)
    if passive:result['family']='CHIP-'+passive[1]
    else:
        m=re.search(r'(?<![A-Z0-9])(LQFP|TQFP|VQFN|WQFN|UQFN|QFN|DFN|QFP|SOIC|TSSOP|VSSOP|MSOP|SSOP|SOP|DIP|PDIP|BGA|LGA|SOT|SOD)[- _]?(\d+)?',s)
        if m:
            family=m[1]
            # SOT-23 is a family code, NOT a 23-pin package.
            if family in ('SOT','SOD'):
                result['family']=family+('-'+m[2] if m[2] else '')
                tail=s[m.end():];n=re.match(r'-(\d+)(?![0-9])',tail)
                if n:result['pin_count']=int(n[1])
            else:
                result['family']=family
                if m[2]:result['pin_count']=int(m[2])
    p=re.search(r'(?:^|_)P(\d+(?:\.\d+)?)MM',s)
    if p:result['pitch_mm']=float(p[1])
    d=re.search(r'(?:^|_)B?(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)(?:X\d+(?:\.\d+)?)?MM',s)
    if d:result['body_mm']=[float(d[1]),float(d[2])]
    if re.search(r'(?:\d+EP|_EP|EXPOSED\s*PAD)',s):result['exposed_pad']=True
    return result


def load_tree(path,limit=64*1024*1024):
    if path.stat().st_size>limit:raise ValueError('Local file exceeds read limit: '+path.name)
    raw=path.read_bytes();return parse(raw.decode('utf-8-sig')),hashlib.sha256(raw).hexdigest()


def pad_data(node):
    pads={};types=set();centres=[]
    for pad in node.nodes('pad'):
        number=pad.val();kind=pad.val(2)
        if not number or kind=='np_thru_hole':continue
        types.add(kind)
        at=pad.one('at');size=pad.one('size')
        data={'number':number,'kind':kind,'at':None,'size':None}
        try:
            if at:data['at']=[float(at.val(1)),float(at.val(2))]
            if size:data['size']=[float(size.val(1)),float(size.val(2))]
        except ValueError:raise ValueError('Non-numeric pad geometry.')
        if data['at'] and not all(math.isfinite(n) for n in data['at']):raise ValueError('Nonfinite pad geometry.')
        pads.setdefault(number,[]).append(data)
        if data['at']:centres.append((number,*data['at']))
    mounting=('SMD' if types=={'smd'} else 'THT' if types=={'thru_hole'} else 'MIXED' if types else None)
    # Report observed collinear spacings only. Do not equate them with package pitch.
    deltas=set()
    if len(centres)<=300:
        for i,(n,x,y) in enumerate(centres):
            for m,u,v in centres[i+1:]:
                if n==m:continue
                if abs(x-u)<1e-6 and abs(y-v)>1e-6:deltas.add(round(abs(y-v),6))
                if abs(y-v)<1e-6 and abs(x-u)>1e-6:deltas.add(round(abs(x-u),6))
    return {'pin_numbers':sorted(pads,key=natural),'unique_electrical_pads':len(pads),
            'mounting':mounting,'pads':pads,'collinear_spacings_mm':sorted(deltas)[:40]}


def symbol_pins(component):
    pins={};issues=[];seen=set()
    for member in component.members:
        libs=member.doc.tree.one('lib_symbols')
        found=next((s for s in (libs.nodes('symbol') if libs else []) if s.val()==component.lib_id),None)
        if found is None:issues.append('Embedded symbol definition not found.');continue
        if found.one('extends'):issues.append('Inherited embedded symbol pin map not resolved.');continue
        try:style=int(member.symbol.get('convert','1'))
        except ValueError:style=1
        def walk(n):
            for child in n.nodes('symbol'):
                match=re.search(r'_(\d+)_(\d+)$',child.val())
                if match and (int(match[1]) not in (0,member.unit) or int(match[2]) not in (0,style)):continue
                yield from walk(child)
            yield from n.nodes('pin')
        for pin in walk(found):
            number=pin.get('number');name=pin.get('name')
            if not number:continue
            if number in pins and pins[number]!=name:issues.append('Stacked pin names conflict at '+number)
            pins[number]=name;seen.add(number)
    return {'pin_numbers':sorted(seen,key=natural),'pin_names':pins,'issues':list(dict.fromkeys(issues))}


class Inspector:
    def __init__(self,ws):
        self.ws=ws;self.cache={};self.issues=[];self.board={};self.libs={}
        settings=ws.state.get('health_settings',{})
        roots=settings.get('library_roots',[])
        self.roots=[Path(p).expanduser() for p in roots]
        envs={'KIPRJMOD':str(ws.project.pro_path.parent)}
        for key in ('KICAD10_FOOTPRINT_DIR','KICAD11_FOOTPRINT_DIR','KICAD9_FOOTPRINT_DIR'):
            if os.environ.get(key):envs[key]=os.environ[key];self.roots.append(Path(os.environ[key]))
        candidates=[Path('/usr/share/kicad/footprints'),Path('/usr/local/share/kicad/footprints')]
        for version in ('10.0','11.0'):
            for root in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)')):
                if root:candidates.append(Path(root)/'KiCad'/version/'share'/'kicad'/'footprints')
        candidates += [Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints')]
        self.roots += [p for p in candidates if p.is_dir()]
        table=ws.project.pro_path.parent/'fp-lib-table'
        if table.is_file():
            try:
                tree,_=load_tree(table,2*1024*1024)
                for lib in tree.nodes('lib'):
                    if lib.get('type') not in ('KiCad',''):continue
                    uri=re.sub(r'\$\{([^}]+)\}',lambda m:envs.get(m[1],m[0]),lib.get('uri'))
                    if '${' in uri or '://' in uri:continue
                    p=Path(uri).expanduser()
                    self.libs[lib.get('name')]=(ws.project.pro_path.parent/p).resolve() if not p.is_absolute() else p
            except (ValueError,OSError) as e:self.issues.append('Footprint table: '+str(e))
        board_path=Path(settings['board_path']).expanduser() if settings.get('board_path') else ws.project.pro_path.with_suffix('.kicad_pcb')
        if board_path.is_file():
            try:
                if board_path.suffix!='.kicad_pcb':raise ValueError('Board path must end in .kicad_pcb')
                tree,hash_=load_tree(board_path)
                if tree.tag!='kicad_pcb':raise ValueError('Not a KiCad PCB.')
                for fp in tree.nodes('footprint'):
                    props=properties(fp);ref=props.get('Reference',('',))[0]
                    if not ref:ref=next((x.val(2) for x in fp.nodes('fp_text') if x.val()=='reference'),'')
                    if not ref:continue
                    self.board.setdefault(ref,[]).append({'name':fp.val(),'source':str(board_path),'hash':hash_,
                        'path':fp.get('path'),'data':pad_data(fp)})
            except (ValueError,OSError) as e:self.issues.append('PCB inspection: '+str(e))

    def library(self,name):
        if name in self.cache:return self.cache[name]
        result={'status':'unavailable','name':name,'hint':package_hint(name)}
        try:
            if ':' not in name:raise ValueError('Footprint must use Library:Name for library lookup.')
            lib,part=name.split(':',1)
            if not lib or not part or any(x in lib+part for x in '/\\') or lib in ('.','..') or part in ('.','..'):raise ValueError('Unsafe/invalid footprint identifier.')
            dirs=[self.libs[lib]] if lib in self.libs else []
            dirs += [root if root.name==lib+'.pretty' else root/(lib+'.pretty') for root in self.roots]
            file=next((d/(part+'.kicad_mod') for d in dirs if (d/(part+'.kicad_mod')).is_file()),None)
            if file:
                tree,hash_=load_tree(file,8*1024*1024)
                if tree.tag!='footprint':raise ValueError('Not a KiCad footprint file.')
                result.update(status='read',source=str(file),hash=hash_,data=pad_data(tree))
        except (ValueError,OSError) as e:result['error']=str(e)
        self.cache[name]=result;return result

    def inspect(self,row):
        name=row['fields'].get('Footprint','');library=self.library(name)
        found=self.board.get(row['ref'],[]);board=found[0] if len(found)==1 else None
        component=self.ws.project.by_id[row['id']]
        pins=symbol_pins(component)
        path_mismatch=bool(board and board['path'] and board['path'].strip('/')!=row['id'].strip('/'))
        return {'library':library,'board':board,'board_ambiguous':len(found)>1,'board_path_mismatch':path_mismatch,
                'symbol':pins,'selected':library.get('data') or (board['data'] if board and board['name']==name and not path_mismatch else None),
                'selected_source':'library' if library.get('data') else 'board (reference matched)' if board and board['name']==name and not path_mismatch else 'name only'}
