"""Evidence-producing acceptance runner; no missing runtime can be a PASS.
Run in the KiCad Python environment for native geometry / GUI checks. All boards
are synthetic disposable fixtures; this command never opens your design files.
"""
import argparse,datetime,hashlib,importlib.util,json,os,pathlib,platform,re,shutil,subprocess,sys,time,traceback,uuid
from .model import Constraint,Rule,RuleDocument,lint
from .catalog import SPECS
from .workspace import Workspace,apply_bundle
from .validation import find_cli,native_drc

HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parent
MANUAL=[
 ('PCM install','Install the exact PCM archive in KiCad 10; verify one plugin registration and native launch.'),
 ('Windows DPI','Test 100/125/150/200 percent on actual Windows displays; inspect every dialog, clipping, keyboard and clipboard behavior.'),
 ('Canvas selection','Select A/B using KiCad tools; cross-probe and focus a violation, change boards and confirm stale rejection.'),
 ('Native resolution','Compare applicable rules, implicit defaults, same-net/local overrides and global floors in the native resolution dialog.'),
 ('Courtyard boundary DRC','Verify inside/outside, touching, crossing, holes and flipped asymmetric courtyards with controlled copper fixtures.'),
 ('Native editing transforms','Move/rotate/flip, duplicate, library-update and redraw courtyard in PCB Editor; save/reopen; managed IDs/scopes must be safe.'),
 ('Workflow usability','Complete BGA exception, matrix, profile migration, undo/redo, signed review, export/native DRC/offline apply with representative boards.'),
]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def fixture():
    return '''(kicad_pcb (version 20241229) (generator "pcbnew")
(general (thickness 1.6))(paper "A4")
(layers (0 "F.Cu" signal)(31 "B.Cu" signal)(36 "B.SilkS" user "b.silkscreen")
(37 "F.SilkS" user "f.silkscreen")(44 "Edge.Cuts" user)(46 "B.CrtYd" user "b.courtyard")(47 "F.CrtYd" user "f.courtyard"))
(setup (pad_to_mask_clearance 0))(net 0 "")
(footprint "CS:Acceptance" (layer "F.Cu") (uuid "b95715e1-757f-470c-ac75-60f57d2d94cb")(at 50 50)
(property "Reference" "U1" (at 0 -4)(layer "F.SilkS")(effects (font (size 1 1)(thickness .15))))
(property "Value" "ACCEPTANCE ONLY" (at 0 4)(layer "F.SilkS")(effects (font (size 1 1)(thickness .15))))
(fp_rect (start -3 -2)(end 2 1)(stroke (width .05)(type default))(fill none)(layer "F.CrtYd"))
(pad "1" smd circle (at 0 0)(size .3 .3)(layers "F.Cu")(net 0 "")(uuid "f9ba0ee2-0495-443f-9a2c-d6c535d61e96")))
(gr_rect (start 40 40)(end 60 60)(stroke (width .05)(type default))(fill none)(layer "Edge.Cuts")))'''


def sample_constraint(spec):
    values={}
    for f in spec.fields:
        if spec.unit in ('count',):values[f]='2'
        elif spec.unit in ('deg',):values[f]='45deg'
        elif spec.unit in ('ratio',):values[f]='1'
        else:values[f]='0.2mm'
    argument=''
    if spec.key=='disallow':argument=spec.choices[0]
    elif spec.key in ('zone_connection','min_resolved_spokes'):argument=spec.choices[0]
    elif spec.key=='assertion':argument="A.Type == 'Pad'"
    return Constraint(spec.key,values,argument)


class Evidence:
    def __init__(self,out):self.out=out;self.rows=[]
    def run(self,name,category,fn=None,skip=None):
        row={'name':name,'category':category};start=time.monotonic()
        if skip:row.update(status='SKIP',detail=skip)
        else:
            try:row.update(status='PASS',detail=fn())
            except Exception as e:row.update(status='FAIL',detail=str(e),traceback=traceback.format_exc())
        row['seconds']=round(time.monotonic()-start,4);self.rows.append(row);print(row['status']+' '+name,flush=True)
        return row
    def native(self,name,board,exe):
        r=native_drc(board,exe,timeout=180);self.record_run(name,r)
        if not accepted_drc(r):raise AssertionError('Native DRC did not return a valid parsed report. See evidence log.')
        return {'returncode':r['returncode'],'note':'Report produced; violations may be intentional. This checks parsing/execution, NOT all constraint semantics.'}
    def record_run(self,name,r):
        path=self.out/(re.sub(r'[^a-zA-Z0-9._-]','_',name)+'.json');path.write_text(json.dumps(r,indent=2),encoding='utf-8')


def accepted_drc(result):
    text=result.get('stdout','')+'\n'+result.get('stderr','')
    bad=bool(re.search(r'(error\s+parsing|parse\s+error|syntax\s+error|unrecognized\s+constraint|unknown\s+constraint)',text,re.I))
    return not bad and result.get('returncode') in (0,5) and isinstance(result.get('data'),dict)


def make_board(directory,text=None):
    directory.mkdir(parents=True,exist_ok=True);board=directory/'acceptance.kicad_pcb';board.write_text(text or fixture(),encoding='utf-8')
    board.with_suffix('.kicad_pro').write_text(json.dumps({'board':{'design_settings':{'rules':{'min_clearance':.1,'min_track_width':.1}}},'net_settings':{'classes':[{'name':'Default','clearance':.2,'track_width':.2}]}}))
    board.with_suffix('.kicad_dru').write_text('(version 1)\n');return board


def core_checks(e):
    def forms():
        for spec in SPECS:
            d=RuleDocument(rules=[Rule('Test '+spec.key,constraints=[sample_constraint(spec)])])
            errors=[i.message for i in lint(d) if i.severity=='error']
            if errors:raise AssertionError(spec.key+': '+'; '.join(errors))
            assert RuleDocument.load(d.emit()).rules[0].constraints[0].kind==spec.key
        return {'forms':len(SPECS),'authority':'local compiler only'}
    e.run('All catalog forms local roundtrip','core',forms)
    def transaction():
        b=make_board(e.out/'offline_fixture');original=b.read_bytes();w=Workspace.load(b)
        w.document.append(Rule('Acceptance width',constraints=[Constraint('track_width',{'min':'.25mm'})]));d=w.export_bundle(e.out/'offline_review');assert b.read_bytes()==original
        try:apply_bundle(d)
        except RuntimeError:pass
        else:raise AssertionError('Open-project attestation not enforced')
        backup=apply_bundle(d,project_closed=True);assert backup and backup.is_dir();assert 'Acceptance width' in b.with_suffix('.kicad_dru').read_text()
        return {'export_did_not_change_source':True,'closed_attestation_enforced':True,'backup_created':True,'fixture_only':True}
    e.run('Offline export/apply transaction','core',transaction)
    def analytic():
        from .field_solver import electrostatic,EPS0
        n=11;fixed={j*n+i:j/(n-1) for j in range(n) for i in range(n) if i in (0,n-1) or j in (0,n-1)}
        c,_,_,res=electrostatic(n,n,.002,.001,[4.]*(n*n),fixed)
        err=abs(c-EPS0*8)/(EPS0*8);assert err<1e-7
        return {'parallel_plate_relative_error':err,'solver_relative_residual':res,'not_SI_signoff':True}
    e.run('Field equation analytic solution','core',analytic)
    def regions():
        from .board import BoardContext
        from .courtyards import stage_regions,check_regions
        b=BoardContext.load(fixture());text,g=stage_regions(b,'U1');assert check_regions(BoardContext.load(text),g)[0]=='current'
        return {'authority':'own parser/compiler; not native serialization'}
    e.run('Owned region local roundtrip','core',regions)


def cli_checks(e,explicit):
    try:
        exe=find_cli(explicit);r=subprocess.run([exe,'version'],capture_output=True,text=True,timeout=20)
        version=(r.stdout or r.stderr).strip()
        if r.returncode or not re.match(r'10\.',version):raise RuntimeError('Native validation requires KiCad 10.x; got '+version)
    except Exception as ex:
        reason=str(ex);e.run('Native KiCad 10 availability','native-cli',skip=reason)
        for spec in SPECS:e.run('Native syntax '+spec.key,'native-cli',skip=reason)
        e.run('Native invalid-rule negative control','native-cli',skip=reason);return
    e.run('Native KiCad 10 availability','native-cli',lambda:{'executable':exe,'version':version})
    board=make_board(e.out/'native_cli_fixture')
    for spec in SPECS:
        def check(spec=spec):
            board.with_suffix('.kicad_dru').write_text(RuleDocument(rules=[Rule('Acceptance '+spec.key,constraints=[sample_constraint(spec)])]).emit(),encoding='utf-8')
            return e.native('syntax_'+spec.key,board,exe)
        e.run('Native syntax '+spec.key,'native-cli',check)
    def invalid():
        board.with_suffix('.kicad_dru').write_text('(version 1)\n(rule "INVALID CONTROL" (constraint NO_SUCH_CONSTRAINT (min 1mm)))\n')
        r=native_drc(board,exe);e.record_run('invalid_rule_control',r)
        if accepted_drc(r):raise AssertionError('Invalid-rule control looked valid. All syntax checks need investigation; do not promote.')
        return {'invalid_rule_rejected':True,'returncode':r['returncode']}
    e.run('Native invalid-rule negative control','native-cli',invalid)


def pcbnew_checks(e):
    try:
        import pcbnew
        if not str(pcbnew.GetBuildVersion()).startswith('10.'):raise RuntimeError('pcbnew is not KiCad 10')
    except Exception as ex:
        for name in ('Native owned linear-area transforms','Native curved-area roundtrip','Native multi-contour roundtrip'):e.run(name,'native-pcbnew',skip=str(ex))
        return
    from .board import BoardContext
    from .courtyards import stage_regions,check_regions
    def roundtrip(shape,transform=False):
        text=fixture()
        if shape!='linear':
            old='(fp_rect (start -3 -2)(end 2 1)(stroke (width .05)(type default))(fill none)(layer "F.CrtYd"))'
            replacement='(fp_circle (center 0 0)(end 2 0)(stroke (width .05)(type default))(fill none)(layer "F.CrtYd"))'
            if shape=='nested':replacement+='(fp_circle (center 0 0)(end 1 0)(stroke (width .05)(type default))(fill none)(layer "F.CrtYd"))'
            text=text.replace(old,replacement)
        text,g=stage_regions(BoardContext.load(text),'U1');b=make_board(e.out/('native_geometry_'+shape),text);board=pcbnew.LoadBoard(str(b));assert board
        pcbnew.SaveBoard(str(b),board)
        state,reason=check_regions(BoardContext.load(b.read_text()),g)
        if state!='current':raise AssertionError(reason)
        if transform:
            fp=next(iter(board.GetFootprints()));fp.Move(pcbnew.VECTOR2I(pcbnew.FromMM(3),pcbnew.FromMM(4)))
            fp.Rotate(fp.GetPosition(),pcbnew.EDA_ANGLE(90,pcbnew.DEGREES_T));fp.Flip(fp.GetPosition(),False)
            pcbnew.SaveBoard(str(b),board);reloaded=pcbnew.LoadBoard(str(b));assert reloaded
            state,reason=check_regions(BoardContext.load(b.read_text()),g)
            if state!='current':raise AssertionError(reason)
        return {'native_load_save':True,'transforms_api_exercised':transform,'interactive_editing_still_manual':True,'board_sha256':sha(b)}
    e.run('Native owned linear-area transforms','native-pcbnew',lambda:roundtrip('linear',True))
    e.run('Native curved-area roundtrip','native-pcbnew',lambda:roundtrip('circle'))
    e.run('Native multi-contour roundtrip','native-pcbnew',lambda:roundtrip('nested'))


def gui_checks(e,enabled):
    if not enabled:e.run('Native wx GUI launch/forms/screenshots','native-gui',skip='Use --gui in a real desktop session; no screenshot fabricated');return
    try:import wx
    except Exception as ex:e.run('Native wx GUI launch/forms/screenshots','native-gui',skip=str(ex));return
    def run():
        from .ui import StudioFrame,ConstraintDialog,BGADialog
        app=wx.GetApp() or wx.App(False);b=make_board(e.out/'gui_fixture');frame=StudioFrame(board_path=str(b));frame.Show();wx.Yield()
        screens=e.out/'screenshots';screens.mkdir(exist_ok=True);saved=[]
        def capture(name):
            wx.Yield();r=frame.GetScreenRect();bmp=wx.Bitmap(r.width,r.height);dc=wx.MemoryDC(bmp);dc.Blit(0,0,r.width,r.height,wx.ScreenDC(),r.x,r.y);dc.SelectObject(wx.NullBitmap);p=screens/(name+'.png');bmp.SaveFile(str(p),wx.BITMAP_TYPE_PNG);saved.append(str(p.relative_to(e.out)))
        try:
            area=wx.GetClientDisplayRect()
            for size in ((1366,768),(1920,1080)):
                frame.SetSize((min(size[0]-24,area.width-24),min(size[1]-64,area.height-40)));frame.Center();wx.Yield()
                for i in range(frame.book.GetPageCount()):frame.book.SetSelection(i);wx.Yield();capture('window_'+str(size[0])+'_page_'+str(i))
            for spec in SPECS:
                d=ConstraintDialog(frame,sample_constraint(spec),frame.w.context,frame.w.netclasses);d.Show();wx.Yield();d.Destroy()
            d=BGADialog(frame,frame.w,'U1');d.Show();wx.Yield();d.Destroy()
            # Screenshots are actual desktop captures. Visual acceptance is NOT inferred.
            return {'wx_version':wx.version(),'display_pixels':[area.width,area.height],'effective_DPI':list(frame.GetDPI()),'screenshots':saved,'all_forms_constructed':len(SPECS),'visual_review_required':True}
        finally:frame.Destroy();wx.Yield()
    e.run('Native wx GUI launch/forms/screenshots','native-gui',run)


def run_acceptance(output,cli='',gui=False):
    out=pathlib.Path(output).expanduser().resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('Choose a NEW or EMPTY evidence folder')
    out.mkdir(parents=True,exist_ok=True);e=Evidence(out)
    core_checks(e);cli_checks(e,cli);pcbnew_checks(e);gui_checks(e,gui)
    for name,detail in MANUAL:e.rows.append({'name':name,'category':'manual-host-acceptance','status':'MANUAL_REQUIRED','detail':detail})
    counts={k:sum(r['status']==k for r in e.rows) for k in ('PASS','FAIL','SKIP','MANUAL_REQUIRED')}
    code=1 if counts['FAIL'] else 2 if counts['SKIP'] or counts['MANUAL_REQUIRED'] else 0
    report={'schema':1,'application':'Constraint Studio','version':'0.3.0','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'environment':{'os':platform.platform(),'python':sys.version,'executable':sys.executable,'display':os.environ.get('DISPLAY','')},'code_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(HERE.glob('*.py'))},'summary':counts,'release_gate':'FAILED' if code==1 else 'INCOMPLETE' if code==2 else 'PASSED','production_qualified':False,'checks':e.rows}
    (out/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['# Constraint Studio 0.3.0 — executed acceptance evidence','',f"Release gate: **{report['release_gate']}**. Native or manual skips are not passes.",'',str(counts),'','| Check | Category | Result |','|---|---|---|']
    lines.extend('| '+r['name']+' | '+r['category']+' | '+r['status']+' |' for r in e.rows)
    (out/'ACCEPTANCE_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(counts));return code


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);parser.add_argument('--cli',default='');parser.add_argument('--gui',action='store_true');a=parser.parse_args(argv)
    try:return run_acceptance(a.output,a.cli,a.gui)
    except Exception as e:print(str(e),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
