"""Read-only native asset capture and content-addressed catalogue bundles.

A capture set binds one observed symbol, footprint and ALL declared models. File
bytes and provenance are separate from derived previews. Missing resources are
reported, not replaced with a guessed similarly-named part. No fonts are stored.
"""
from __future__ import annotations
from pathlib import Path, PureWindowsPath
from copy import deepcopy
import base64
import ctypes
import ctypes.util
import gzip
import hashlib
import io
import json
import math
import os
import re
import sys
import zipfile
from .sexpr import parse, quote, properties, apply_edits

MAX_ASSET = 64 * 1024 * 1024
MAX_DOCUMENT = 192 * 1024 * 1024
MAX_CAPTURE = 256 * 1024 * 1024
MODEL_EXTENSIONS = {'.step','.stp','.stpz','.stepz','.wrl','.wrz','.stl','.obj','.iges','.igs','.brep'}
FONT_EXTENSIONS = {'.ttf','.otf','.woff','.woff2','.ttc'}
HASH = re.compile(r'[a-f0-9]{64}')
SEED = 0xABBA2345


def sha(raw): return hashlib.sha256(raw).hexdigest()

def fingerprint(value):
    return sha(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())


def murmur128(raw, legacy=False):
    """Public-domain MurmurHash3 x64/128 math, KiCad word-order rendering.

    Legacy verification reproduces the historical padded-tail *length*, without
    hashing an artificial extra block. Modern and historical hashes are accepted
    for reading only. Our exports use original bytes, not newly embedded hashes.
    """
    mask=(1<<64)-1; c1=0x87c37b91114253d5; c2=0x4cf5ad432745937f
    rot=lambda x,n:((x<<n)|(x>>(64-n)))&mask
    mix1=lambda x:(rot((x*c1)&mask,31)*c2)&mask
    mix2=lambda x:(rot((x*c2)&mask,33)*c1)&mask
    def fm(x):
        x^=x>>33;x=(x*0xff51afd7ed558ccd)&mask;x^=x>>33;x=(x*0xc4ceb9fe1a85ec53)&mask
        return x^(x>>33)
    h1=h2=SEED;full=len(raw)//16*16
    for offset in range(0,full,16):
        h1^=mix1(int.from_bytes(raw[offset:offset+8],'little'))
        h1=(rot(h1,27)+h2)&mask;h1=(h1*5+0x52dce729)&mask
        h2^=mix2(int.from_bytes(raw[offset+8:offset+16],'little'))
        h2=(rot(h2,31)+h1)&mask;h2=(h2*5+0x38495ab5)&mask
    tail=raw[full:];length=len(raw)
    if legacy and tail:
        padding=4-(len(tail)+4)%4;length+=padding;tail+=b'\0'*padding
    tail=tail[:length%16]
    if len(tail)>8:h2^=mix2(int.from_bytes(tail[8:],'little'))
    if tail:h1^=mix1(int.from_bytes(tail[:8],'little'))
    h1^=length;h2^=length;h1=(h1+h2)&mask;h2=(h2+h1)&mask
    h1=fm(h1);h2=fm(h2);h1=(h1+h2)&mask;h2=(h2+h1)&mask
    return f'{h1:016X}{h2:016X}'


def zstd_decode(raw, limit=MAX_ASSET):
    """Bounded decoding through python-zstandard or a system/KiCad zstd library.

    Never load a DLL from a project directory or from a model-supplied path.
    """
    try:
        import zstandard
    except ImportError:
        zstandard=None
    if zstandard:
        size=zstandard.frame_content_size(raw)
        if size<0 or size>limit:raise ValueError('Invalid/oversized Zstandard frame.')
        return zstandard.ZstdDecompressor().decompress(raw,max_output_size=limit)
    names=[]
    system=ctypes.util.find_library('zstd')
    if system:names.append(system)
    if os.name=='nt':
        for pf in (os.environ.get('ProgramFiles',''),os.environ.get('ProgramFiles(x86)','')):
            if pf:
                for v in ('10.0','11.0','9.0'):
                    for n in ('libzstd.dll','zstd.dll','libzstd-1.dll'):
                        p=Path(pf)/'KiCad'/v/'bin'/n
                        if p.is_file():names.append(str(p))
    for name in names:
        try:
            z=ctypes.CDLL(name)
            z.ZSTD_getFrameContentSize.argtypes=[ctypes.c_void_p,ctypes.c_size_t];z.ZSTD_getFrameContentSize.restype=ctypes.c_ulonglong
            z.ZSTD_decompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t];z.ZSTD_decompress.restype=ctypes.c_size_t
            z.ZSTD_isError.argtypes=[ctypes.c_size_t];z.ZSTD_isError.restype=ctypes.c_uint
            source=ctypes.create_string_buffer(raw);size=z.ZSTD_getFrameContentSize(source,len(raw))
            if size>limit:raise ValueError('Unknown or oversized embedded Zstandard frame.')
            target=ctypes.create_string_buffer(max(1,size));result=z.ZSTD_decompress(target,size,source,len(raw))
            if z.ZSTD_isError(result) or result!=size:raise ValueError('Invalid embedded Zstandard payload.')
            return target.raw[:result]
        except (OSError,AttributeError):continue
    raise ValueError('Embedded-file decoder unavailable. Install requirements-assets.txt in this Python interpreter (zstandard), then re-harvest.')


def embedded_file(name, containers):
    """Resolve nearest scope first; a corrupt nearer payload cannot fall through.

    Each container is (tree, original_text, source_filename). A nested metadata-
    only record can defer to the owning board's payload if its checksum matches.
    """
    expected=''
    for tree,text,source in containers:
        table=tree.one('embedded_files')
        if not table:continue
        matches=[x for x in table.nodes('file') if x.get('name')==name]
        if not matches:continue
        if len(matches)!=1:raise ValueError('Ambiguous embedded filename: '+name)
        item=matches[0];checksum=item.get('checksum');kind=item.get('type')
        if kind=='font' or Path(name).suffix.lower() in FONT_EXTENSIONS:raise ValueError('Font files are excluded from the catalogue.')
        if expected and checksum and expected.casefold()!=checksum.casefold():raise ValueError('Nested/owner embedded checksums disagree: '+name)
        expected=checksum or expected;data=item.one('data')
        if data is None:continue
        encoded=text[data.start:data.end]
        match=re.fullmatch(r'\(data\s*\|([A-Za-z0-9+/=\s]*)\|\s*\)',encoded,re.S)
        if not match:
            if re.fullmatch(r'\(data\s*\)',encoded):continue
            raise ValueError('Unsupported embedded data encoding: '+name)
        packed=base64.b64decode(re.sub(r'\s','',match[1]),validate=True)
        if len(packed)>MAX_ASSET:raise ValueError('Embedded compressed payload exceeds 64 MiB.')
        raw=zstd_decode(packed)
        if len(expected)==64:valid=sha(raw).casefold()==expected.casefold();algorithm='sha256'
        elif len(expected)==32:
            valid=expected.upper() in (murmur128(raw),murmur128(raw,True));algorithm='KiCad MMH3 (modern/legacy)'
        else:valid=False;algorithm='unsupported'
        if not valid:raise ValueError('Embedded checksum missing, unsupported or invalid: '+name)
        return raw,{'source':str(source),'embedded_name':name,'checksum':expected,'checksum_algorithm':algorithm}
    raise FileNotFoundError('Embedded payload not available in footprint/board/schematic scope: '+name)


def sanitize_native(text):
    """Never retain font payloads. Non-model attachments are outside this capture.

    Model references and their original model data are preserved. Removing a font
    does not remove the text/face name. View rendering uses browser system fonts.
    """
    tree=parse(text);edits=[]
    def walk(node):
        for child in node.children:
            if child.tag=='embedded_files':
                for item in child.nodes('file'):
                    name=item.get('name');ext=Path(name).suffix.lower()
                    if item.get('type')=='font' or ext in FONT_EXTENSIONS or ext not in MODEL_EXTENSIONS:
                        edits.append((item.start,item.end,''))
            elif child.tag=='embedded_fonts':edits.append((child.start,child.end,'(embedded_fonts no)'))
            else:walk(child)
    walk(tree)
    return apply_edits(text,edits)


def options(value=None):
    out={'symbol_roots':[],'footprint_roots':[],'model_roots':[],'variables':{},'path_aliases':{},'footprint_source':'board_first'}
    if value is not None:
        if not isinstance(value,dict) or set(value)-set(out):raise ValueError('Unknown asset-resolution option.')
        out.update(deepcopy(value))
    for k in ('symbol_roots','footprint_roots','model_roots'):
        if not isinstance(out[k],list) or len(out[k])>100 or any(not isinstance(x,str) or not x.strip() or len(x)>4096 for x in out[k]):raise ValueError(k+': choose up to 100 local directories.')
    for k in ('variables','path_aliases'):
        if not isinstance(out[k],dict) or len(out[k])>200:raise ValueError('Invalid '+k)
        for n,v in out[k].items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',n) or not isinstance(v,str) or '\0' in v or len(v)>4096:raise ValueError('Invalid variable/path alias.')
    if 'KIPRJMOD' in out['variables']:raise ValueError('KIPRJMOD is fixed to the harvested project.')
    if out['footprint_source'] not in ('library_first','board_first'):raise ValueError('Choose library_first or board_first.')
    return out


class Resolver:
    def __init__(self,ws,settings=None):
        self.ws=ws;self.root=ws.project.pro_path.parent;self.options=options(settings)
        self.sources={};self.cache={};self.notes=[];self.tables={'symbol':{},'footprint':{}}
        self.env={};self.roots={'symbol':[],'footprint':[],'model':[]};self.board=None
        self.explicit_roots={kind:[Path(x).expanduser() for x in self.options[kind+'_roots']] for kind in self.roots}
        self.explicit_roots['footprint']=[Path(x).expanduser() for x in ws.state.get('health_settings',{}).get('library_roots',[])]+self.explicit_roots['footprint']
        self._config()
        self.env.update({k:v for k,v in os.environ.items() if isinstance(v,str)})
        self.env.update(ws.project.variables)
        for k,v in ws.state.get('project_variables',{}).items():
            if v is None:self.env.pop(k,None)
            else:self.env[k]=v
        self.env.update(self.options['variables']);self.env['KIPRJMOD']=str(self.root)
        common=[Path('/usr/share/kicad'),Path('/usr/local/share/kicad'),Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport')]
        for v in ('10.0','11.0','9.0'):
            for pf in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)')):
                if pf:common.append(Path(pf)/'KiCad'/v/'share'/'kicad')
        for kind,dirname,suffix in [('symbol','symbols','SYMBOL_DIR'),('footprint','footprints','FOOTPRINT_DIR'),('model','3dmodels','3DMODEL_DIR')]:
            for v in ('10','11','9'):
                key=f'KICAD{v}_{suffix}'
                if key in self.env:self.roots[kind].append(Path(self.expand(self.env[key])))
                else:
                    p=next((r/dirname for r in common if (r/dirname).is_dir()),None)
                    if p:self.env[key]=str(p)
            self.roots[kind]+=[r/dirname for r in common if (r/dirname).is_dir()]
            self.roots[kind]=[Path(x).expanduser() for x in self.options[kind+'_roots']]+self.roots[kind]
        self.roots['footprint']=[Path(x).expanduser() for x in ws.state.get('health_settings',{}).get('library_roots',[])]+self.roots['footprint']
        for folder in [*self.config_dirs,self.root]:
            for kind,filename in [('symbol','sym-lib-table'),('footprint','fp-lib-table')]:
                table=folder/filename
                if table.is_file():
                    try:
                        tree,_=self.read_tree(table,4*1024*1024)
                        for lib in tree.nodes('lib'):
                            if lib.get('type') not in ('KiCad',''):continue
                            self.tables[kind][lib.get('name')]=(lib.get('uri'),self.root)
                    except (OSError,ValueError) as exc:self.notes.append(str(exc))
        board=Path(ws.state.get('health_settings',{}).get('board_path') or ws.project.pro_path.with_suffix('.kicad_pcb')).expanduser()
        if board.is_file():
            try:
                tree,text=self.read_tree(board)
                if tree.tag!='kicad_pcb':raise ValueError('Not a KiCad PCB.')
                self.board=(tree,text,board)
            except (OSError,ValueError) as exc:self.notes.append('Board capture: '+str(exc))

    def _config(self):
        if os.name=='nt':base=Path(os.environ.get('APPDATA',Path.home()/'AppData'/'Roaming'))/'kicad'
        elif sys.platform=='darwin':base=Path.home()/'Library'/'Preferences'/'kicad'
        else:base=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'kicad'
        # Oldest first; current stable (10) takes precedence over installed preview.
        self.config_dirs=[base/v for v in ('9.0','11.0','10.0')]
        if os.environ.get('KICAD_CONFIG_HOME'):self.config_dirs.append(Path(os.environ['KICAD_CONFIG_HOME']).expanduser())
        for folder in self.config_dirs:
            p=folder/'kicad_common.json'
            if not p.is_file():continue
            try:
                raw=self.read(p,4*1024*1024);data=json.loads(raw.decode('utf-8-sig'))
                vs=data.get('environment',{}).get('vars',{})
                if isinstance(vs,dict):self.env.update({k:v for k,v in vs.items() if isinstance(k,str) and isinstance(v,str)})
            except (ValueError,OSError) as exc:self.notes.append('KiCad path settings: '+str(exc))

    def read(self,path,limit=MAX_DOCUMENT):
        p=Path(path).expanduser().resolve()
        if p.suffix.lower() in FONT_EXTENSIONS:raise ValueError('Font capture is not permitted.')
        if p in self.cache:
            if len(self.cache[p][0])>limit:raise ValueError('Cached asset exceeds requested size bound.')
            return self.cache[p][0]
        if not p.is_file():raise FileNotFoundError(str(p))
        if p.stat().st_size>limit:raise ValueError('Asset/document exceeds capture limit: '+p.name)
        raw=p.read_bytes()
        if len(raw)>limit:raise ValueError('Asset/document grew beyond capture limit.')
        self.cache[p]=(raw,None);self.sources[str(p)]=sha(raw)
        return raw

    def read_tree(self,path,limit=MAX_DOCUMENT):
        p=Path(path).expanduser().resolve();raw=self.read(p,limit)
        if self.cache[p][1] is None:self.cache[p]=(raw,parse(raw.decode('utf-8-sig')))
        return self.cache[p][1],raw.decode('utf-8-sig')

    def expand(self,value):
        seen=set()
        for _ in range(32):
            if value in seen:raise ValueError('Cyclic path variable: '+value)
            seen.add(value)
            def replace(m):
                key=m[1]
                if key not in self.env:raise ValueError('Unresolved path variable: '+key)
                return self.env[key]
            new=re.sub(r'\$\{([^{}]+)\}',replace,value)
            if new==value:
                if '${' in new:raise ValueError('Malformed path variable: '+new)
                return new
            value=new
        raise ValueError('Path variable recursion limit.')

    def path(self,uri,base=None,kind='model'):
        if not isinstance(uri,str) or not uri or len(uri)>4096 or '\0' in uri:raise ValueError('Invalid asset path.')
        alias=re.match(r'^:([A-Za-z_][A-Za-z0-9_]*):(.*)$',uri)
        if alias:
            if alias[1] not in self.options['path_aliases']:raise ValueError('Configure legacy 3D path alias: '+alias[1])
            uri=str(Path(self.options['path_aliases'][alias[1]])/alias[2].lstrip('/\\'))
        expanded=self.expand(uri).replace('\\','/')
        if '://' in expanded:raise ValueError('Remote/embedded URI is not a local path: '+uri)
        p=Path(expanded).expanduser()
        if os.name!='nt' and PureWindowsPath(expanded).is_absolute():raise ValueError('Windows path unavailable on this system; configure variables/roots and re-harvest: '+uri)
        if p.is_absolute():
            if p.is_file():return p.resolve()
            # Do not replace an absolute path with a same-basename unrelated asset.
            raise FileNotFoundError('Asset path does not exist: '+str(p))
        choices=[(base or self.root)/p,self.root/p]
        choices += [r/p for r in self.roots[kind]]
        # A relative path is anchored to its project/containing file first.
        for x in choices[:2]:
            if x.is_file():return x.resolve()
        existing=list(dict.fromkeys(x.resolve() for x in choices[2:] if x.is_file()))
        if len(existing)==1:return existing[0]
        if len(existing)>1:raise ValueError('Ambiguous asset in configured roots: '+uri)
        raise FileNotFoundError('Asset not found: '+uri)

    def library_file(self,identifier,kind):
        if ':' not in identifier:raise ValueError('Expected Library:Name for '+kind+'.')
        lib,name=identifier.split(':',1)
        if not lib or not name or any(c in lib+name for c in '/\\') or lib in ('.','..') or name in ('.','..'):raise ValueError('Unsafe library identifier.')
        # Deliberately selected workspace roots override globally installed tables.
        suffix='.kicad_sym' if kind=='symbol' else '.pretty'
        explicit=[]
        for root in self.explicit_roots[kind]:
            candidate=root if root.name==lib+suffix else root/(lib+suffix)
            if kind=='footprint':candidate=candidate/(name+'.kicad_mod')
            if candidate.is_file():explicit.append(candidate.resolve())
        explicit=list(dict.fromkeys(explicit))
        if len(explicit)>1:raise ValueError('Ambiguous '+kind+' library: '+identifier)
        if explicit:return explicit[0],name
        if lib in self.tables[kind]:
            uri,base=self.tables[kind][lib]
            expanded=self.expand(uri).replace('\\','/')
            if expanded.startswith('kicad-embed://'):return expanded,name
            p=Path(expanded).expanduser()
            if not p.is_absolute():p=base/p
            if kind=='footprint':p=p/(name+'.kicad_mod')
            if not p.is_file():raise FileNotFoundError('Configured library entry is missing: '+str(p))
            return p.resolve(),name
        suffix='.kicad_sym' if kind=='symbol' else '.pretty'
        choices=[]
        for root in self.roots[kind]:
            p=root if root.name==lib+suffix else root/(lib+suffix)
            if kind=='footprint':p=p/(name+'.kicad_mod')
            if p.is_file():choices.append(p.resolve())
        choices=list(dict.fromkeys(choices))
        if len(choices)!=1:raise ValueError(('Ambiguous' if choices else 'Unavailable')+' '+kind+' library: '+identifier)
        return choices[0],name

    def symbol(self,row):
        comp=self.ws.project.by_id[row['id']];member=comp.members[0]
        doc=member.doc;ls=doc.tree.one('lib_symbols')
        sym=next((n for n in ls.nodes('symbol') if n.val()==comp.lib_id),None) if ls else None
        containers=[(doc.tree,doc.text,doc.path)];source=str(doc.path)
        if sym:raw=doc.text[sym.start:sym.end];pool={n.val():doc.text[n.start:n.end] for n in ls.nodes('symbol')}
        else:
            file,name=self.library_file(comp.lib_id,'symbol')
            if isinstance(file,str) and file.startswith('kicad-embed://'):
                data,_=embedded_file(file[14:],containers);txt=data.decode('utf-8-sig');tree=parse(txt)
            else:tree,txt=self.read_tree(file);source=str(file)
            pool={n.val():txt[n.start:n.end] for n in tree.nodes('symbol')};raw=pool.get(name)
            if not raw:raise ValueError('Symbol not present in resolved library: '+comp.lib_id)
        chain=[]
        def resolve_parent(current,seen):
            parent=parse(current).get('extends')
            if not parent:return current
            if parent in seen or len(seen)>32:raise ValueError('Symbol inheritance cycle/depth limit.')
            chain.append(parent);base=pool.get(parent) or pool.get(comp.lib_id.split(':')[0]+':'+parent)
            if base is None:
                f,name=self.library_file(comp.lib_id.split(':')[0]+':'+parent,'symbol');t,txt=self.read_tree(f)
                pool.update({n.val():txt[n.start:n.end] for n in t.nodes('symbol')});base=pool.get(name)
            if not base:raise ValueError('Symbol parent cannot be resolved: '+parent)
            return flatten_symbol(resolve_parent(base,seen+[parent]),current)
        current=resolve_parent(raw,[])
        current=sanitize_native(current)
        return asset('symbol',comp.lib_id,current.encode(),source,source_hash=self.sources.get(source),inherited_from=chain),containers

    def footprint(self,row):
        name=row['fields'].get('Footprint','');board_error='';library_error=''
        def board():
            if not self.board:raise ValueError('No saved board available.')
            tree,text,file=self.board;found=[]
            for f in tree.nodes('footprint'):
                path=f.get('path').strip('/')
                if path!=row['id'].strip('/'):continue
                if f.val()!=name:raise ValueError('Saved board footprint differs from selected footprint.')
                found.append(f)
            if len(found)!=1:raise ValueError('Saved board UUID mapping missing or ambiguous.')
            f=found[0];content=text[f.start:f.end];a=asset('footprint',name,sanitize_native(content).encode(),str(file),source_hash=self.sources[str(file)],representation='board-footprint')
            return a,[(f,text,file),(tree,text,file)]
        def library():
            if name.startswith('kicad-embed://'):
                containers=[(m.doc.tree,m.doc.text,m.doc.path) for m in self.ws.project.by_id[row['id']].members]
                if self.board:containers.append(self.board)
                raw,meta=embedded_file(name[14:],containers);tree=parse(raw.decode('utf-8-sig'))
                return asset('footprint',name,sanitize_native(raw.decode('utf-8-sig')).encode(),meta['source'],source_hash=self.sources.get(meta['source']),representation='library-footprint'),[(tree,raw.decode('utf-8-sig'),Path(meta['source'])),*containers]
            file,_=self.library_file(name,'footprint')
            if isinstance(file,str) and file.startswith('kicad-embed://'):raise ValueError('Embedded footprint-directory library tables are unsupported; link a .kicad_mod payload directly.')
            tree,text=self.read_tree(file)
            if tree.tag!='footprint':raise ValueError('Not a modern KiCad footprint.')
            a=asset('footprint',name,sanitize_native(text).encode(),str(file),source_hash=self.sources[str(file)],representation='library-footprint')
            return a,[(tree,text,file)]
        methods=[library,board] if self.options['footprint_source']=='library_first' else [board,library]
        errors=[]
        for method in methods:
            try:return (*method(),errors)
            except (ValueError,OSError) as exc:errors.append(method.__name__+': '+str(exc))
        raise ValueError('; '.join(errors))


def flatten_symbol(parent,child):
    """Flatten ordinary KiCad extends: child's properties/scalars override parent.

    Graphics are inherited unless the child declares graphics with the same unit
    and alternate style. Unknown nested extensions remain preserved as nodes.
    """
    p=parse(parent);c=parse(child);name=c.val();nodes={};order=[]
    def key(n):
        if n.tag=='property':return ('property',n.val())
        if n.tag=='symbol':
            m=re.search(r'(_\d+_\d+)$',n.val())
            return ('symbol',m[1] if m else n.val())
        return (n.tag,'')
    for text,root in [(parent,p),(child,c)]:
        for n in root.children:
            if n.tag=='extends':continue
            k=key(n)
            if k not in order:order.append(k)
            s=text[n.start:n.end]
            if n.tag=='symbol':
                tail=re.search(r'(_\d+_\d+)$',n.val())
                if tail:s=apply_edits(s,[(n.atoms[1].start-n.start,n.atoms[1].end-n.start,quote(name+tail[1]))])
            nodes[k]=s
    return '(symbol '+quote(name)+'\n'+'\n'.join(nodes[k] for k in order)+'\n)'


def asset(kind,name,raw,source,**extra):
    if len(raw)>MAX_ASSET:raise ValueError('Asset exceeds 64 MiB: '+name)
    a={'kind':kind,'name':name,'hash':sha(raw),'source':str(source),'size':len(raw),**{k:v for k,v in extra.items() if v is not None}}
    if kind in ('symbol','footprint'):a['text']=raw.decode('utf-8')
    else:a['data_b64']=base64.b64encode(raw).decode('ascii');a['extension']=Path(name).suffix.lower()
    return a


def payload(a):
    """Validate reviewed asset bodies before committing, including old v0.6 plans."""
    if a.get('kind') not in ('symbol','footprint','model'):raise ValueError('Unexpected captured asset kind.')
    if 'data_b64' in a:
        if not isinstance(a['data_b64'],str) or len(a['data_b64'])>MAX_ASSET*4//3+8:raise ValueError('Model payload exceeds capture limit.')
        raw=base64.b64decode(a['data_b64'],validate=True)
    elif isinstance(a.get('text'),str):raw=a['text'].encode('utf-8')
    else:raise ValueError('Missing captured asset bytes.')
    if len(raw)>MAX_ASSET or sha(raw)!=a.get('hash'):raise ValueError('Harvest asset hash/size mismatch.')
    if a['kind']=='model' and a.get('extension',Path(a['name']).suffix.lower()) not in MODEL_EXTENSIONS:raise ValueError('Unsupported model file type; arbitrary files and fonts cannot be imported.')
    if a['kind'] in ('symbol','footprint'):
        txt=raw.decode('utf-8-sig');tree=parse(txt)
        if tree.tag!=a['kind']:raise ValueError('Native asset type mismatch.')
        if sanitize_native(txt)!=txt:raise ValueError('Unfiltered non-model embedded content in asset. Re-harvest with v0.7.')
    return raw


def xyz(node,default):
    v=node.one('xyz') if node else None
    if not v:return list(default)
    values=[float(v.val(i)) for i in (1,2,3)]
    if not all(math.isfinite(x) and abs(x)<=1e6 for x in values):raise ValueError('Invalid model transform.')
    return values


def capture(resolver,row,variant):
    """Return independent raw assets and one coherent observation set."""
    assets=[];issues=[];scope=[]
    aset={'schema':'wayricad-asset-set-1','project':str(resolver.ws.project.pro_path),'instance':row['id'],'reference':row['ref'],'variant':variant,
          'symbol_hash':None,'footprint_hash':None,'symbol_name':resolver.ws.project.by_id[row['id']].lib_id,
          'footprint_name':row['fields'].get('Footprint',''),'models':[],'issues':issues,'capture_version':'0.7.0'}
    try:
        a,scope=resolver.symbol(row);assets.append(a);aset['symbol_hash']=a['hash']
    except (ValueError,OSError) as exc:issues.append({'kind':'symbol','status':'missing','message':str(exc)})
    if aset['footprint_name']:
        try:
            a,containers,fallbacks=resolver.footprint(row);assets.append(a);aset['footprint_hash']=a['hash'];aset['footprint_representation']=a['representation'];aset['footprint_source']=a['source']
            aset['resolution_notes']=fallbacks
            ft=parse(a['text']);model_scope=[*containers,*scope]
            if resolver.board and resolver.board not in model_scope:model_scope.append(resolver.board)
            for index,m in enumerate(ft.nodes('model')):
                info={'index':index,'uri':m.val(),'name':Path(m.val().replace('\\','/')).name,'hash':None,'status':'missing',
                      'offset':xyz(m.one('offset'),(0,0,0)),'rotation':xyz(m.one('rotate'),(0,0,0)),'scale':xyz(m.one('scale'),(1,1,1)),
                      'visible':not any(x.value=='hide' for x in m.atoms) and m.get('hide','no') not in ('yes','true')}
                try:
                    ext=Path(info['name']).suffix.lower()
                    if ext not in MODEL_EXTENSIONS:raise ValueError('Unsupported declared 3D file extension: '+ext)
                    uri=m.val()
                    if uri.startswith('kicad-embed://'):
                        raw,meta=embedded_file(uri[14:],model_scope)
                    else:
                        path=resolver.path(uri,Path(a['source']).parent,'model');raw=resolver.read(path,MAX_ASSET);meta={'source':str(path),'source_hash':sha(raw)}
                    ma=asset('model',info['name'],raw,**meta)
                    if ma['hash'] not in {x['hash'] for x in assets}:assets.append(ma)
                    info.update(hash=ma['hash'],status='stored',source=meta['source'],extension=ext)
                    dependencies=model_dependency_warnings(raw,ext)
                    if dependencies:
                        info['dependency_warnings']=dependencies
                        issues.extend({'kind':'model_dependency','status':'unsupported','name':info['name'],'message':v} for v in dependencies)
                    if 'embedded_name' in meta:info['embedded_name']=meta['embedded_name']
                except (ValueError,OSError) as exc:
                    info['error']=str(exc);issues.append({'kind':'model','status':'missing','name':info['name'],'message':str(exc)})
                aset['models'].append(info)
        except (ValueError,OSError) as exc:issues.append({'kind':'footprint','status':'missing','message':str(exc)})
    else:aset['footprint_representation']='not_assigned'
    aset['id']=fingerprint(aset)
    return assets,aset


def read_blob(lib,h):
    if not isinstance(h,str) or not HASH.fullmatch(h):raise ValueError('Invalid asset hash.')
    r=lib.db.execute('SELECT body FROM assets WHERE hash=?',(h,)).fetchone()
    if not r or len(r[0])>MAX_ASSET or sha(r[0])!=h:raise ValueError('Catalogue asset missing, oversized or corrupt: '+h)
    return bytes(r[0])


def asset_sets(part):
    existing=part.get('asset_sets',[])
    if existing:return existing
    # v0.6 catalogue: retain compatibility but do not pretend its models exist.
    symbols=[a for a in part.get('assets',[]) if a['kind']=='symbol']
    footprints=[a for a in part.get('assets',[]) if a['kind']=='footprint' and a.get('name')==part['fields'].get('Footprint')]
    return [{'id':'legacy','schema':'wayricad-asset-set-1','symbol_hash':symbols[0]['hash'] if len(symbols)==1 else None,
             'footprint_hash':footprints[0]['hash'] if len(footprints)==1 else None,'models':[],'reference':part.get('reference_hint',''),
             'symbol_name':part['fields'].get('LibrarySymbol',''),'footprint_name':part['fields'].get('Footprint',''),
             'footprint_representation':'library-footprint','issues':[{'kind':'model','status':'unknown','message':'Captured before v0.7: re-harvest to retain referenced model bytes.'}],
             'capture_version':'legacy','project':'','variant':''}]


def select_set(part,set_id=None):
    sets=asset_sets(part)
    if set_id:
        match=[x for x in sets if x['id']==set_id]
        if len(match)!=1:raise ValueError('Unknown or ambiguous asset set.')
        return match[0]
    # Prefer complete sets. Deterministic; multiple *different* usable assemblies
    # require explicit selection on export, but browsing may show the first.
    return sorted(sets,key=lambda s:(not bool(s.get('symbol_hash')),not bool(s.get('footprint_hash')),bool(s.get('issues')),s.get('id','')))[0]


def summary(part):
    sets=asset_sets(part);syms={x.get('symbol_hash') for x in sets}-{None};fps={x.get('footprint_hash') for x in sets}-{None}
    models={m.get('hash') for x in sets for m in x.get('models',[]) if m.get('status')=='stored'}-{None}
    required=sum(len(x.get('models',[])) for x in sets);missing=sum(m.get('status')!='stored' for x in sets for m in x.get('models',[]))
    complete=any(x.get('symbol_hash') and (x.get('footprint_hash') or not x.get('footprint_name')) and not x.get('issues') for x in sets)
    return {'symbol':len(syms),'footprint':len(fps),'model':len(models),'sets':len(sets),'missing_models':missing,
            'model_state':'partial' if models and missing else 'stored' if models else 'missing' if required else 'not_captured' if any(x.get('capture_version')=='legacy' for x in sets) else 'not_assigned',
            'complete_references':complete,'notice':'Stored assets are not qualified components; no assigned 3D model is different from a broken 3D link.'}


def describe(lib,pid,revision=None,set_id=None):
    p=lib.get(pid,revision);s=select_set(p,set_id)
    return {'schema':'wayricad-asset-browser-1','part_id':pid,'revision':p['revision'],'internal_pn':p.get('internal_pn'),
            'summary':summary(p),'sets':asset_sets(p),'selected':s,
            'assets':[{k:v for k,v in a.items() if k not in ('text','data_b64')} for a in p.get('assets',[])],
            'preview_notice':'Derived inspection views are not KiCad rendering or land-pattern qualification. Original captured files are kept separately.'}


def normalize_footprint(raw):
    """Detach a front-side board footprint from placement; retain local geometry.

    Back-side board copies are stored, but native export refuses normalization
    until a library counterpart or a KiCad-normalized front-side copy is supplied.
    """
    s=raw.decode('utf-8-sig');t=parse(s)
    if t.tag!='footprint':raise ValueError('Not a modern footprint.')
    board=bool(t.one('at'))
    if board and t.get('layer')!='F.Cu':raise ValueError('Back-side board footprint retained; select a library asset or normalize in KiCad before library export.')
    angle=float(t.one('at').val(3,'0')) if t.one('at') else 0
    edits=[]
    for n in t.children:
        if n.tag in ('at','path','uuid','tstamp','sheetname','sheetfile','embedded_files','embedded_fonts','zone','group'):
            edits.append((n.start,n.end,''));continue
        # Board pad and displayed text angles are absolute; positions are local.
        if board and n.tag in ('pad','property','fp_text') and n.one('at'):
            at=n.one('at')
            if len(at.atoms)>3:edits.append((at.atoms[3].start,at.atoms[3].end,format(float(at.val(3))-angle,'.12g')))
            elif angle:edits.append((at.end-1,at.end-1,' '+format(-angle,'.12g')))
        for child in n.children:
            if child.tag in ('uuid','tstamp','net','pinfunction','pintype'):edits.append((child.start,child.end,''))
    return apply_edits(s,edits)


def export_library(lib,ids,choices=None,require_complete=False,model_prefix='${KIPRJMOD}/WayriCAD.3dshapes',library_name='WayriCAD'):
    """Portable selected native definitions + all captured referenced model bytes."""
    from .partsdb import PROTECTED
    if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)):raise ValueError('Select 1..10,000 unique catalog parts.')
    if not isinstance(model_prefix,str) or len(model_prefix)>4096 or any(c in model_prefix for c in '\r\n\0"') or '://' in model_prefix:raise ValueError('Invalid local model-path prefix.')
    if not isinstance(library_name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',library_name):raise ValueError('Library nickname must start with a letter and use letters, digits, underscore or hyphen (64 characters maximum).')
    choices=choices or {};files={};symbols=[];mapping=[];warnings=[]
    for pid in ids:
        p=lib.get(pid);sets=asset_sets(p);s=select_set(p,choices.get(pid));stem='KW_'+pid[2:]
        usable={fingerprint([x.get('symbol_hash'),x.get('footprint_hash'),[{k:m.get(k) for k in ('hash','index','offset','scale','rotation','visible','uri')} for m in x.get('models',[])]]) for x in sets if x.get('symbol_hash') and x.get('footprint_name')==p['fields'].get('Footprint','')}
        if len(usable)>1 and pid not in choices:raise ValueError('Several observed asset assemblies for '+p['internal_pn']+'; choose one set explicitly.')
        if not s.get('symbol_hash'):

            if require_complete:raise ValueError('Missing captured symbol: '+p['internal_pn'])
            warnings.append({'id':pid,'reason':'Missing captured symbol; omitted.'});continue
        if s.get('footprint_name')!=p['fields'].get('Footprint',''):raise ValueError('Chosen captured footprint differs from current catalog Footprint field.')
        issues=deepcopy(s.get('issues',[]))
        if require_complete and issues:raise ValueError('Incomplete captured references: '+p['internal_pn']+'; re-harvest/resolve assets first.')
        raw=read_blob(lib,s['symbol_hash']).decode('utf-8-sig');t=parse(raw);edits=[(t.atoms[1].start,t.atoms[1].end,quote(stem))]
        def rename(n):
            for child in n.nodes('symbol'):
                tail=re.search(r'(_\d+_\d+)$',child.val())
                if tail:edits.append((child.atoms[1].start,child.atoms[1].end,quote(stem+tail[1])))
                rename(child)
        rename(t)
        # No independent auxiliary or font payloads belong in this three-asset export.
        for n in t.nodes('embedded_files'):edits.append((n.start,n.end,''))
        props=properties(t);fields={k:v for k,v in p['fields'].items() if k not in PROTECTED and k!='LibrarySymbol' and '${' not in k and '${' not in v}
        fields.update(InternalPN=p['internal_pn'],WayriCADCatalogID=pid,WayriCADCatalogRevision=str(p['revision']))
        model_files=[]
        if s.get('footprint_hash'):
            fptext=normalize_footprint(read_blob(lib,s['footprint_hash']));ft=parse(fptext);fedits=[(ft.atoms[1].start,ft.atoms[1].end,quote(stem))]
            models=s.get('models',[])
            for index,m in enumerate(ft.nodes('model')):
                found=next((x for x in models if x.get('index')==index and x.get('uri')==m.val()),None)
                if found and found.get('hash'):
                    ext=found.get('extension') or Path(found.get('name','')).suffix.lower()
                    if ext not in MODEL_EXTENSIONS:raise ValueError('Invalid model extension in catalogue metadata.')
                    name=found['hash']+ext;dest=library_name+'.3dshapes/'+name
                    files[dest]=read_blob(lib,found['hash']);model_files.append(dest)
                    fedits.append((m.atoms[1].start,m.atoms[1].end,quote(model_prefix.rstrip('/')+'/'+name)))
                else:
                    if require_complete:raise ValueError('Missing 3D payload: '+m.val())
                    # Explicit partial export retains original broken link and warns.
                    issues.append({'kind':'model','status':'missing','message':'Original unresolved link retained: '+m.val()})
            files[library_name+'.pretty/'+stem+'.kicad_mod']=apply_edits(fptext,fedits).encode();fields['Footprint']=library_name+':'+stem
        elif s.get('footprint_name'):
            if require_complete:raise ValueError('Missing captured footprint: '+p['internal_pn'])
            issues.append({'kind':'footprint','message':'Original footprint link retained.'})
        for k,v in fields.items():
            if k in props:
                a=props[k][2];edits.append((a.start,a.end,quote(v)))
            else:edits.append((t.end-1,t.end-1,f'\n(property {quote(k)} {quote(v)} (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))\n'))
        symbols.append(apply_edits(raw,edits));mapping.append({'part_id':pid,'revision':p['revision'],'asset_set':s['id'],'symbol':library_name+':'+stem,'footprint':fields.get('Footprint',''),'models':model_files,'complete_references':not issues})
        warnings.extend({'id':pid,**x} for x in issues)
    if not symbols:raise ValueError('No unambiguous captured native symbol assets to export.')
    files[library_name+'.kicad_sym']=('(kicad_symbol_lib (version 20241209) (generator "wayricad_bom_studio")\n'+'\n'.join(symbols)+'\n)').encode()
    files['catalog-data.json']=json.dumps({'parts':[lib.get(x) for x in ids],'mapping':mapping,'warnings':warnings},indent=2,ensure_ascii=False).encode()
    files['README.txt']=('Extract at your project root for the default ${KIPRJMOD}/WayriCAD.3dshapes links. Add WayriCAD.kicad_sym and WayriCAD.pretty in KiCad library tables using nickname WayriCAD. For a global folder, export with a configured path-variable prefix instead. No library table is overwritten. Original 3D bytes and model transforms are retained; blob filenames use SHA-256 to prevent collisions. Review source redistribution rights. Stored/previewed is not qualified. Read catalog-data.json for every missing reference. Native KiCad host loading still requires validation.\nModel prefix: '+model_prefix+'\n').encode()
    files['manifest.json']=json.dumps({'schema':'wayricad-native-library-export-2','files':{k:sha(v) for k,v in files.items()},'warnings':warnings,'complete_references':not warnings},indent=2).encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
    return out.getvalue(),library_name+'_native_library.zip','application/zip'


def validate_sets(part):
    assets=part.get('assets',[])
    if len(assets)>20000 or len(part.get('asset_sets',[]))>20000:raise ValueError('Too many captured assets or observation sets.')
    known={}
    for a in assets:
        if not isinstance(a,dict) or a.get('kind') not in ('symbol','footprint','model') or not HASH.fullmatch(a.get('hash','')):raise ValueError('Invalid catalogue asset descriptor.')
        known.setdefault(a['hash'],set()).add(a['kind'])
    seen=set()
    for s in part.get('asset_sets',[]):
        if not isinstance(s,dict) or s.get('schema')!='wayricad-asset-set-1' or not HASH.fullmatch(s.get('id','')):raise ValueError('Invalid observation set.')
        if s['id'] in seen:raise ValueError('Duplicate observation set ID.')
        seen.add(s['id'])
        if s['id']!=fingerprint({k:v for k,v in s.items() if k!='id'}):raise ValueError('Observation set fingerprint mismatch.')
        for key,kind in [('symbol_hash','symbol'),('footprint_hash','footprint')]:
            h=s.get(key)
            if h and kind not in known.get(h,set()):raise ValueError('Asset set refers to an absent '+kind+'.')
        if not isinstance(s.get('models'),list) or len(s['models'])>200:raise ValueError('Invalid model reference list.')
        for m in s['models']:
            if m.get('hash') and 'model' not in known.get(m['hash'],set()):raise ValueError('Model reference is not in the captured asset set.')
    return True


def download_asset(lib,pid,h,revision=None):
    p=lib.get(pid,revision);a=next((a for a in p.get('assets',[]) if a.get('hash')==h),None)
    if not a:raise ValueError('Asset does not belong to this part revision.')
    ext='.kicad_sym' if a['kind']=='symbol' else '.kicad_mod' if a['kind']=='footprint' else a.get('extension',Path(a['name']).suffix.lower())
    raw=read_blob(lib,h)
    if a['kind']=='symbol':raw=b'(kicad_symbol_lib (version 20241209) (generator "wayricad_bom_studio")\n'+raw+b'\n)'
    return raw,('captured_'+h[:16]+ext),'application/octet-stream'


def model_dependency_warnings(raw,ext):
    """Conservative closure check; never fetch scripts, textures or linked models.
    Stored original bytes are retained even when this flags an unsupported bundle.
    """
    from .meshpreview import unpack
    try:data,kind=unpack(raw,ext)
    except (ValueError,OSError,zipfile.BadZipFile) as exc:return ['Compressed model dependency closure could not be checked: '+str(exc)]
    if kind=='.wrl' and re.search(rb'\b(?:Inline|ImageTexture|MovieTexture|Script)\s*\{',data):return ['VRML contains a texture, external-node or script declaration. Its auxiliary files are not harvested or executed; use a self-contained model.']
    if kind=='.obj' and re.search(rb'^\s*mtllib\s+',data,re.M):return ['OBJ refers to an external material library; material/texture dependencies are not harvested.']
    if kind in ('.step','.stp') and (b'EXTERNAL_SOURCE' in data.upper() or b'EXTERNALLY_DEFINED_REPRESENTATION' in data.upper()):return ['STEP declares an external document dependency. Only the referenced root file is stored; supply a self-contained STEP assembly.']
    return []


def read_harvest_plan(path):
    """Only asset-bearing CLI harvest plans get the larger bounded input budget.
    All other CLI/API JSON inputs keep their 20 MiB limit and strict-key policy.
    """
    from .automation import strict_loads
    import sys
    limit=384*1024*1024
    if path=='-':text=sys.stdin.read(limit+1)
    else:
        p=Path(path).expanduser()
        if p.stat().st_size>limit:raise ValueError('Asset harvest plan exceeds 384 MiB.')
        text=p.read_text(encoding='utf-8-sig')
    value=strict_loads(text,max_bytes=limit)
    if isinstance(value,dict) and value.get('schema')=='wayricad-cli-1':value=value.get('data')
    if not isinstance(value,dict) or value.get('schema')!='wayricad-harvest-1':raise ValueError('Expected wayricad-harvest-1 asset plan.')
    return value


def write_asset_new(path,raw,suggested_name):
    """Explicit asset export only; allow new native library files, never designs.
    Exclusive creation refuses existing files and dangling symlinks. Output must
    retain the file type, so captured bytes cannot be disguised as a script.
    """
    p=Path(path).expanduser();ext=Path(suggested_name).suffix.lower()
    if p.suffix.lower()!=ext or ext not in MODEL_EXTENSIONS|{'.kicad_sym','.kicad_mod'}:raise ValueError('Asset output must use its original '+ext+' extension.')
    if p.exists() or p.is_symlink():raise FileExistsError('Output already exists; choose a new path.')
    if not p.parent.is_dir():raise FileNotFoundError('Output parent directory does not exist.')
    with open(p,'xb') as f:
        try:f.write(raw);f.flush();os.fsync(f.fileno())
        except BaseException:
            f.close()
            try:p.unlink()
            except OSError:pass
            raise
    return str(p.resolve())
