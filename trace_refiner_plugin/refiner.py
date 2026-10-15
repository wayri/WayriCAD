"""Source-bound, conservative native track refinement with independent DRC gates."""
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from pathlib import Path
import fnmatch
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
import sys
from .geometry import simplify_local, _covered, _collapse, _length

DEFAULTS = dict(scope='selected tracks', nets=[], layers=[], groups=[],
                max_deviation=.10, max_shortening=.10,
                protected='*CLK*,*CLOCK*,*DDR*,*DQS*,*USB*,*PCIE*,*LVDS*,*RF*,*CAN*')


def uid(item):
    return item.m_Uuid.AsString()


def point(item, end=False):
    p = item.GetEnd() if end else item.GetStart()
    return p.x, p.y


def copy_board(board, api):
    """Serialize/reload a detached board; BOARD(parent) is not a copy constructor."""
    with tempfile.TemporaryDirectory(prefix='wayricad-refine-copy-') as directory:
        path=Path(directory)/'board.kicad_pcb'
        if not api.SaveBoard(str(path),board,True):raise RuntimeError('Could not snapshot the PCB.')
        return api.LoadBoard(str(path))


def snapshot(board, api):
    """Hash complete native serialization without changing the live board filename."""
    with tempfile.TemporaryDirectory(prefix='wayricad-refine-hash-') as directory:
        path=Path(directory)/'board.kicad_pcb'
        if not api.SaveBoard(str(path),board,True):
            raise RuntimeError('Could not snapshot the current PCB.')
        selected=sorted(uid(t) for t in board.GetTracks() if t.IsSelected())
        selected+=sorted(uid(p) for fp in board.GetFootprints() for p in fp.Pads() if p.IsSelected() or fp.IsSelected())
        return hashlib.sha256(path.read_bytes()+json.dumps([selected,native_rules(board)]).encode()).hexdigest()


def native_rules(board):
    """Bind live scalar Board Setup rules and effective net-class dimensions."""
    settings=board.GetDesignSettings();state={}
    # Do not reflect over SWIG object properties: some return unowned native
    # allocations. These scalar dimensions govern existing copper acceptance.
    for key in ('m_MinClearance','m_TrackMinWidth','m_CopperEdgeClearance',
                'm_HoleClearance','m_HoleToHoleMin','m_MaxError','m_MinConn',
                'm_MinGrooveWidth','m_MinResolvedSpokes','m_ViasMinSize',
                'm_ViasMinAnnularWidth','m_MinThroughDrill','m_MicroViasMinSize',
                'm_MicroViasMinDrill','m_SolderMaskExpansion','m_SolderMaskMinWidth',
                'm_SolderMaskToCopperClearance','m_AllowSoldermaskBridgesInFPs'):
        if hasattr(settings,key):state[key]=getattr(settings,key)
    classes=[]
    ns=settings.m_NetSettings
    names={t.GetNetname() for t in board.GetTracks()}
    names.update(p.GetNetname() for fp in board.GetFootprints() for p in fp.Pads())
    names.update(z.GetNetname() for z in board.Zones())
    for name in sorted(names):
        nc=ns.GetEffectiveNetClass(name);values=[]
        for getter in ('GetName','GetClearance','GetTrackWidth','GetDiffPairWidth','GetDiffPairGap','GetDiffPairViaGap','GetViaDiameter','GetViaDrill'):
            method=getattr(nc,getter,None)
            if method:values.append((getter,method()))
        classes.append((name,values))
    state['netclasses']=classes
    return state


def project_inputs(board):
    if not board.GetFileName():raise ValueError('Save the PCB and project before opening Trace Refiner.')
    source=Path(board.GetFileName())
    return [source.with_suffix(ext) for ext in ('.kicad_pro','.kicad_dru')]


def rule_hash(board):
    return tuple((str(p),hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
                 for p in project_inputs(board))


def patterns(value):
    return [p.strip() for p in value.split(',') if p.strip()]


def matches(value, globs):
    return any(fnmatch.fnmatchcase(value.casefold(),p.casefold()) for p in globs)


def protected_net(name, globs):
    # Native differential pair conventions. Arbitrary critical nets are user-protected.
    return matches(name,globs) or bool(re.search(r'(_[pn]|[+-])$',name,re.I))


def connectivity(board, api):
    """Native connected-component partitions of unchanged pads, vias and zones."""
    board.BuildConnectivity()
    conn=board.GetConnectivity()
    terminals=[p for fp in board.GetFootprints() for p in fp.Pads()]
    terminals += [t for t in board.GetTracks() if isinstance(t,api.PCB_VIA)]
    terminals += list(board.Zones())
    identities={uid(t) for t in terminals};visited=set();partitions=[]
    for terminal in terminals:
        if uid(terminal) in visited:continue
        # This API returns the transitive connected set, not just neighbours.
        # Traversing it again per track makes large ground nets quadratic.
        connected={uid(item) for item in conn.GetConnectedItems(terminal)}
        connected.add(uid(terminal));visited.update(connected)
        members=connected & identities
        if members:partitions.append(tuple(sorted(members)))
    return tuple(sorted(partitions))


@dataclass
class Change:
    originals: list
    before: list
    after: list
    net: str
    layer: int
    width: int
    added: list = field(default_factory=list)


@dataclass
class Plan:
    fingerprint: str
    rules: tuple
    settings: dict
    changes: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    validated: bool = False
    evidence: dict = field(default_factory=dict)


def propose(board, api, settings=None, progress=None):
    """Build bounded, endpoint-preserving proposals; does not modify the board."""
    options=dict(DEFAULTS);options.update(settings or {})
    if options['scope'] not in ('selected tracks','selected nets','whole board','net filters','groups'):
        raise ValueError('Choose a supported scope.')
    for key in ('max_deviation','max_shortening'):
        if not math.isfinite(float(options[key])) or not 0<float(options[key])<=1:
            raise ValueError(key+' must be greater than zero and at most 1 mm.')
    inputs=project_inputs(board)
    if inputs[1].is_file() and re.search(r'\(constraint\s+(?:length|skew|diff_pair_gap|diff_pair_uncoupled)\b',inputs[1].read_text(encoding='utf-8')):
        raise ValueError('Custom length, skew or differential-pair rules are present. This first version preserves this board; use native routing for constrained nets.')
    result=Plan(snapshot(board,api),rule_hash(board),options)
    tracks=list(board.GetTracks());selected_nets={t.GetNetname() for t in tracks if t.IsSelected()}
    selected_nets.update(p.GetNetname() for fp in board.GetFootprints() for p in fp.Pads() if p.IsSelected() or fp.IsSelected())
    globs=patterns(options['protected'])
    all_names={t.GetNetname() for t in tracks}
    all_names.update(p.GetNetname() for fp in board.GetFootprints() for p in fp.Pads())
    all_names.update(z.GetNetname() for z in board.Zones());paired=set()
    for name in all_names:
        match=re.search(r'([pPnN])(?=_?\d*$)',name)
        if match:
            char=match.group();other=('N' if char=='P' else 'P' if char=='N' else 'n' if char=='p' else 'p')
            if name[:match.start()]+other+name[match.end():] in all_names:paired.add(name)
    groups=set(options['groups'])
    def allowed(t):
        if type(t) is not api.PCB_TRACK or t.IsLocked() or not t.GetNetname():return False
        if t.GetParentGroup() is not None:return False
        if options['layers'] and t.GetLayerName() not in options['layers']:return False
        if t.GetNetname() in paired or protected_net(t.GetNetname(),globs):return False
        scope=options['scope']
        return (scope=='whole board' or scope=='selected tracks' and t.IsSelected()
                or scope=='selected nets' and t.GetNetname() in selected_nets
                or scope=='net filters' and t.GetNetname() in options['nets']
                or scope=='groups' and t.GetNetClassName() in groups)
    # Topology uses all original track endpoints. Scope boundaries are anchors.
    adjacency=defaultdict(list)
    for t in tracks:
        if type(t) is api.PCB_TRACK:
            for p in (point(t),point(t,True)):adjacency[(t.GetNetCode(),t.GetLayer(),p)].append(t)
    anchors=defaultdict(list)
    for fp in board.GetFootprints():
        for pad in fp.Pads():anchors[pad.GetNetCode()].append(pad)
    for t in tracks:
        if isinstance(t,api.PCB_VIA):anchors[t.GetNetCode()].append(t)
    def continuation(t,p):
        neighbours=adjacency[(t.GetNetCode(),t.GetLayer(),p)]
        if len(neighbours)!=2:return None
        other=next((x for x in neighbours if uid(x)!=uid(t)),None)
        if other is None or not allowed(other) or other.GetWidth()!=t.GetWidth():return None
        v=api.VECTOR2I(*p)
        for anchor in anchors[t.GetNetCode()]:
            if anchor.IsOnLayer(t.GetLayer()) and anchor.GetBoundingBox().Contains(v):return None
        return other
    copper_by_net=defaultdict(list)
    for t in tracks:copper_by_net[t.GetNetCode()].append(t)
    visited=set();deadline=time.monotonic()+30
    eligible=sorted((t for t in tracks if allowed(t)),key=uid)
    for index,first in enumerate(eligible):
        if progress and progress(f'Inspecting routing {index+1}/{len(eligible)}') is False:raise ValueError('Preview cancelled; board unchanged.')
        if time.monotonic()>deadline:
            result.skipped.append(('Search budget','30-second planning budget reached; remaining routing is unchanged. Narrow the scope.'));break
        if uid(first) in visited:continue
        chain=[first];points=[point(first),point(first,True)]
        for front in (True,False):
            while len(chain)<128:
                current=chain[0] if front else chain[-1];p=points[0] if front else points[-1]
                other=continuation(current,p)
                if other is None or uid(other) in {uid(x) for x in chain}:break
                q=point(other,True) if point(other)==p else point(other)
                if front:chain.insert(0,other);points.insert(0,q)
                else:chain.append(other);points.append(q)
        visited.update(uid(t) for t in chain)
        if len(chain)<2:continue
        if len(chain)>=128 or points[0]==points[-1]:
            result.skipped.append((first.GetNetname(),'Long chain or loop preserved'));continue
        # Preserve mid-segment T connections, crossing contacts and pad/via contacts.
        own={uid(t) for t in chain};unsafe=False
        for item in copper_by_net[first.GetNetCode()]:
            if uid(item) in own or item.GetNetCode()!=first.GetNetCode() or not item.IsOnLayer(first.GetLayer()):continue
            shape=item.GetEffectiveShape()
            other_width=item.GetWidth(first.GetLayer()) if isinstance(item,api.PCB_VIA) else item.GetWidth()
            radius=(first.GetWidth()+other_width)/2+2
            for a,b in zip(points,points[1:]):
                dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
                head=radius if a==points[0] else 0
                tail=radius if b==points[-1] else 0
                # Copper inside a fixed endpoint's capsule remains connected
                # regardless of the new exit direction. All other contacts
                # (including first/last-segment T joints) are immutable.
                if length<=head+tail:continue
                start=api.VECTOR2I(round(a[0]+dx*head/length),round(a[1]+dy*head/length))
                end=api.VECTOR2I(round(b[0]-dx*tail/length),round(b[1]-dy*tail/length))
                if shape.Collide(api.SEG(start,end),first.GetWidth()//2):unsafe=True;break
            if unsafe:break
        # A pad touching the moving portion is immutable, even off its centre.
        for pad in anchors[first.GetNetCode()]:
            if not pad.IsOnLayer(first.GetLayer()):continue
            shape=pad.GetEffectiveShape(first.GetLayer()) if isinstance(pad,api.PAD) else pad.GetEffectiveShape()
            if any(shape.Collide(api.VECTOR2I(*p),first.GetWidth()//2) for p in (points[0],points[-1])):continue
            if any(shape.Collide(api.SEG(api.VECTOR2I(*a),api.VECTOR2I(*b)),first.GetWidth()//2)
                   for a,b in zip(points,points[1:])):unsafe=True
        if unsafe:
            result.skipped.append((first.GetNetname(),'Interior copper contact preserved'));continue
        mm=[(api.ToMM(x),api.ToMM(y)) for x,y in points]
        replacement=simplify_local(mm,float(options['max_deviation']),float(options['max_shortening']))
        if not replacement:continue
        after=[(round(x*1e6),round(y*1e6)) for x,y in replacement]
        if after==points:continue
        # Integer rounding must retain exact terminal anchors.
        after[0],after[-1]=points[0],points[-1]
        actual=[(api.ToMM(x),api.ToMM(y)) for x,y in after]
        shortening=_length(_collapse(mm))-_length(_collapse(actual))
        if (not -1e-9<=shortening<=options['max_shortening'] or
                not _covered(mm,actual,options['max_deviation']) or
                not _covered(actual,mm,options['max_deviation'])):continue
        result.changes.append(Change(chain,points,after,first.GetNetname(),first.GetLayer(),first.GetWidth()))
    if snapshot(board,api)!=result.fingerprint:raise ValueError('Board changed during planning. Preview again.')
    return result


def materialize(board,api,changes):
    """Replace only reviewed chains; keep first UUID, endpoints, net, layer and width."""
    for change in changes:
        originals=change.originals
        if not change.added:
            for i,(a,b) in enumerate(zip(change.after,change.after[1:])):
                t=originals[min(i,len(originals)-1)].Duplicate()
                if i==0:t.SetUuid(originals[0].m_Uuid)
                t.SetStart(api.VECTOR2I(*a));t.SetEnd(api.VECTOR2I(*b));t.ClearSelected()
                change.added.append(t)
        for t in originals:board.Remove(t)
        for t in change.added:board.Add(t)
    board.BuildConnectivity()


def findings(report):
    def key(v):return v.get('type'),tuple(sorted(i.get('uuid','') for i in v.get('items',[]))),v.get('severity')
    return {key(v) for category in ('violations','unconnected_items') for v in report.get(category,[])}


def require_comparable_baseline(report):
    """Do not accept a diff against a potentially capped native report."""
    counts=Counter(v.get('type') for category in ('violations','unconnected_items') for v in report.get(category,[]))
    excessive=[str(kind) for kind,count in counts.items() if count>=199]
    if excessive:
        raise ValueError('Baseline DRC has 199 or more findings of one type ('+', '.join(sorted(excessive))+'). Resolve these existing findings first; report limits/order prevent a reliable no-new-violations check.')


def validate_detached(board,api,preview,progress=None,evidence_dir=None):
    """Run native analysis outside the PCB Editor, with cancellation and timeout."""
    if snapshot(board,api)!=preview.fingerprint or rule_hash(board)!=preview.rules:raise ValueError('Board or rules changed. Preview again.')
    source=Path(board.GetFileName())
    if not source.is_file() or not source.with_suffix('.kicad_pro').is_file():raise ValueError('Save the PCB and matching project before validation.')
    candidates=[Path(sys.executable),Path(api.__file__).resolve().parents[2]/'python.exe']
    python=next((p for p in candidates if p.is_file() and p.name.lower().startswith('python')),None)
    if python is None:raise ValueError('Matching native KiCad Python was not found; validation is unavailable.')
    with tempfile.TemporaryDirectory(prefix='wayricad-refiner-worker-') as directory:
        directory=Path(directory);path=directory/source.name
        api.SaveBoard(str(path),board,True)
        for context in project_inputs(board):
            if context.is_file():shutil.copy2(context,directory/context.name)
        request=directory/'request.json';result=directory/'result.json'
        payload=dict(board=str(path),settings=preview.settings,rules=native_rules(board),evidence_dir=str(Path(evidence_dir).resolve()) if evidence_dir else None,changes=[dict(ids=[uid(t) for t in c.originals],before=c.before,after=c.after,net=c.net,layer=c.layer,width=c.width) for c in preview.changes])
        request.write_text(json.dumps(payload),encoding='utf-8')
        process=subprocess.Popen([str(python),str(Path(__file__).with_name('worker.py')),str(request),str(result)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=sys.platform!='win32')
        deadline=time.monotonic()+360
        try:
            while True:
                if progress and progress('Checking detached candidate connectivity and native DRC…') is False:raise ValueError('Validation cancelled; board unchanged.')
                if time.monotonic()>deadline:raise TimeoutError('Detached validation exceeded six minutes; Apply remains blocked.')
                try:stdout,stderr=process.communicate(timeout=.15);break
                except subprocess.TimeoutExpired:pass
        except BaseException:
            if sys.platform=='win32':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                import os,signal
                os.killpg(process.pid,signal.SIGKILL)
            process.communicate();raise
        if not result.is_file():raise RuntimeError('Native validation worker did not complete. Apply remains blocked. '+(stderr or stdout)[-300:])
        response=json.loads(result.read_text(encoding='utf-8'))
        if process.returncode or not response.get('validated'):raise ValueError(response.get('error','Native validation failed; Apply remains blocked.'))
        if snapshot(board,api)!=preview.fingerprint or rule_hash(board)!=preview.rules:raise ValueError('Board or rules changed during validation. Preview again.')
        preview.evidence=response['evidence'];preview.validated=True
    return preview


def validate(board,api,preview,cli=None,progress=None,evidence_dir=None):
    """Independent native connectivity and before/after DRC, with matching saved rules."""
    if snapshot(board,api)!=preview.fingerprint or rule_hash(board)!=preview.rules:raise ValueError('Board or rules changed. Preview again.')
    source=Path(board.GetFileName())
    if not source.is_file() or not source.with_suffix('.kicad_pro').is_file():
        raise ValueError('Save the PCB and its project first; native DRC needs the matching .kicad_pro.')
    cli=cli or str(Path(sys.executable).resolve().parent/('kicad-cli.exe' if sys.platform=='win32' else 'kicad-cli'))
    if not Path(cli).is_file():cli=shutil.which('kicad-cli')
    if not cli:raise ValueError('KiCad CLI was not found. Install the matching KiCad 10 command-line tools.')
    with tempfile.TemporaryDirectory(prefix='wayricad-trace-refiner-') as directory:
        directory=Path(directory);baseline=copy_board(board,api);candidate=copy_board(board,api)
        # The production worker verifies live versus saved Board Setup before
        # this stage. Never attach a temporary SETTINGS_MANAGER project to
        # editor-owned boards: its native pointers outlive the Python manager.
        by_id={uid(t):t for t in candidate.GetTracks()}
        changes=[Change([by_id[uid(t)] for t in c.originals],c.before,c.after,c.net,c.layer,c.width) for c in preview.changes]
        before_partition=connectivity(baseline,api);materialize(candidate,api,changes)
        if connectivity(candidate,api)!=before_partition:raise ValueError('Candidate changes native pad/via/zone connectivity; Apply is blocked.')
        reports={}
        evidence_dir=Path(evidence_dir) if evidence_dir else None
        if evidence_dir:evidence_dir.mkdir(parents=True,exist_ok=False)
        for label,copy in (('baseline',baseline),('candidate',candidate)):
            folder=directory/label;folder.mkdir();path=folder/source.name
            for context in project_inputs(board):
                if context.is_file():shutil.copy2(context,folder/context.name)
            api.SaveBoard(str(path),copy)
            output=folder/'drc.json'
            process=subprocess.Popen([str(cli),'pcb','drc','--format','json','--severity-all','--all-track-errors','--refill-zones','-o',str(output),str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+180
            try:
                while True:
                    if progress and progress('Native DRC: '+label) is False:raise ValueError('Validation cancelled; board unchanged.')
                    if time.monotonic()>deadline:raise TimeoutError('Native DRC exceeded three minutes; board unchanged.')
                    try:stdout,stderr=process.communicate(timeout=.15);break
                    except subprocess.TimeoutExpired:pass
            except BaseException:
                process.kill();process.communicate();raise
            if process.returncode or not output.is_file():raise RuntimeError('Native DRC did not complete: '+(stderr or stdout)[-600:])
            reports[label]=json.loads(output.read_text(encoding='utf-8'))
            if evidence_dir:shutil.copytree(folder,evidence_dir/label)
            if label=='baseline':require_comparable_baseline(reports[label])
        affected={uid(t) for c in preview.changes for t in c.originals}
        if any(i.get('uuid') in affected for category in ('violations','unconnected_items')
               for finding in reports['baseline'].get(category,[]) for i in finding.get('items',[])):
            raise ValueError('A proposed chain already has native DRC findings. Restrict the scope to clean routing before refining.')
        # Candidate uses source first-track UUIDs; map added replacement UUIDs back
        # before comparing existing findings. New findings still block acceptance.
        mapping={uid(t):uid(c.originals[0]) for c in changes for t in c.added}
        for category in ('violations','unconnected_items'):
            for finding in reports['candidate'].get(category,[]):
                for item in finding.get('items',[]):item['uuid']=mapping.get(item.get('uuid'),item.get('uuid'))
        new=findings(reports['candidate'])-findings(reports['baseline'])
        if new:raise ValueError(f'Candidate has {len(new)} new native DRC/connectivity findings; Apply is blocked. Reduce scope or displacement.')
        preview.evidence=dict(baseline=len(findings(reports['baseline'])),candidate=len(findings(reports['candidate'])),new_findings=0,connectivity='unchanged')
    if snapshot(board,api)!=preview.fingerprint or rule_hash(board)!=preview.rules:raise ValueError('Board or rules changed during validation. Preview again.')
    preview.validated=True
    return preview


class Transaction:
    """Window-owned native history; stale inputs block Apply, Undo and Redo."""
    def __init__(self,board,api,preview):
        if not preview.validated:raise ValueError('Validate with native DRC before Apply.')
        self.board,self.api,self.preview=board,api,preview;self.applied=False;self.expected=preview.fingerprint
    def check(self):
        if snapshot(self.board,self.api)!=self.expected or rule_hash(self.board)!=self.preview.rules:raise ValueError('Board or project rules changed; operation blocked.')
    def redo(self):
        self.check()
        if self.applied:raise ValueError('Already applied.')
        # Journal each object operation so partial failures can be reversed.
        if not all(c.added for c in self.preview.changes):
            for c in self.preview.changes:
                c.added=[]
                for i,(a,b) in enumerate(zip(c.after,c.after[1:])):
                    clone=c.originals[min(i,len(c.originals)-1)].Duplicate()
                    if i==0:clone.SetUuid(c.originals[0].m_Uuid)
                    clone.SetStart(self.api.VECTOR2I(*a));clone.SetEnd(self.api.VECTOR2I(*b));clone.ClearSelected();c.added.append(clone)
        self._exchange(True)
        try:expected=snapshot(self.board,self.api)
        except Exception:
            self._exchange(False);raise
        self.applied=True;self.expected=expected;return self
    def undo(self):
        self.check()
        if not self.applied:raise ValueError('Not applied.')
        self._exchange(False)
        try:expected=snapshot(self.board,self.api)
        except Exception:
            self._exchange(True);raise
        self.applied=False;self.expected=expected
    def _exchange(self,forward):
        journal=[]
        try:
            for c in self.preview.changes:
                remove,add=(c.originals,c.added) if forward else (c.added,c.originals)
                for t in remove:self.board.Remove(t);journal.append(lambda t=t:self.board.Add(t))
                for t in add:self.board.Add(t);journal.append(lambda t=t:self.board.Remove(t))
            self.board.BuildConnectivity()
        except Exception as original:
            failures=[]
            for inverse in reversed(journal):
                try:inverse()
                except Exception as exc:failures.append(str(exc))
            self.board.BuildConnectivity()
            if failures:raise RuntimeError('Recovery needs inspection: '+'; '.join(failures)) from original
            raise
