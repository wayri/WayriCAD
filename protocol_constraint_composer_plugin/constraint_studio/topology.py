"""Explicit series-component/xNet constraint planning, not copper-field extraction.

A through-component connection exists only after the user declares two pads and
its delay. Native fromTo rules are emitted separately for each real KiCad net.
No resistor, inductor, connector or active device is silently treated as a short.
"""
from dataclasses import dataclass, asdict
import math
from .sexpr import scalar
from .expressions import function_test
from .model import Rule, Constraint, RuleDocument, lint
from .profiles import replace_generated
from .engineering import fingerprint

@dataclass(frozen=True)
class Endpoint:
    name: str
    reference: str
    pad: str
    net: str
    uuid: str


def endpoints(context):
    netmap={scalar(n):n.children[2].value for n in context.root.find('net') if len(n.children)>2} if context.root else {}
    result={}
    for fp in context.footprints:
        for p in fp.node.find('pad'):
            net=p.first('net')
            name=fp.reference+'-'+scalar(p)
            n=net.children[2].value if net and len(net.children)>2 else netmap.get(scalar(net),'')
            if name in result:
                # Multiple physical pads may share one pin number; don't guess one.
                result[name]=None
            else: result[name]=Endpoint(name,fp.reference,scalar(p),n,scalar(p.first('uuid')))
    return result


def _number(x):
    x=float(x)
    if not math.isfinite(x) or x<0:raise ValueError('Delay/budget values must be finite and nonnegative')
    return x


def series_path(context,source,sink,bridges):
    pts=endpoints(context)
    def point(name):
        p=pts.get(name)
        if p is None or not p.net:raise ValueError('Unknown, ambiguous or unconnected pad: '+name)
        return p
    a,b=point(source),point(sink)
    graph={};normalized=[];used=set()
    for bridge in bridges:
        x,y=point(bridge['from']),point(bridge['to'])
        if x.reference!=y.reference or x.pad==y.pad:raise ValueError('A pass-through must identify two distinct pads on the same component')
        if x.net==y.net:raise ValueError('Pass-through pads are already on the same native net')
        if x.name in used or y.name in used:raise ValueError('One pad occurs in multiple pass-through declarations')
        used.update((x.name,y.name))
        delay=_number(bridge.get('delay_ps',0));i=len(normalized)
        normalized.append({'from':x.name,'to':y.name,'delay_ps':delay})
        graph.setdefault(x.net,[]).append((y.net,i,x,y))
        graph.setdefault(y.net,[]).append((x.net,i,y,x))
    paths=[]
    def visit(net,seen,steps):
        if len(paths)>1:return
        if len(steps)>64:raise ValueError('Logical signal path exceeds 64 pass-throughs')
        if net==b.net:paths.append(steps);return
        for target,i,x,y in graph.get(net,[]):
            if target not in seen:visit(target,seen|{target},steps+[(i,x,y)])
    visit(a.net,{a.net},[])
    if not paths:raise ValueError('No path through the explicitly declared components')
    if len(paths)>1:raise ValueError('Multiple logical paths found; resolve the topology explicitly')
    current=a;segments=[];delay=0;selected=[]
    for i,x,y in paths[0]:
        if current.name!=x.name:segments.append({'net':current.net,'from':current.name,'to':x.name})
        delay+=normalized[i]['delay_ps'];selected.append(normalized[i]);current=y
    if current.name!=b.name:segments.append({'net':current.net,'from':current.name,'to':b.name})
    if not segments:raise ValueError('The requested endpoints do not span a PCB segment')
    netset={s['net'] for s in segments}
    extra=[p.name for p in pts.values() if p and p.net in netset and p.name not in {x for s in segments for x in (s['from'],s['to'])}]
    return {'source':source,'sink':sink,'segments':segments,'bridges':selected,'component_delay_ps':delay,
            'other_pads_on_path_nets':extra,'authority':'declared-logical-connectivity',
            'warning':'Not copper-path extraction. Additional pads, stubs, zones and parallel copper paths require native fromTo/DRC evaluation.'}


def compile_path(context,source,sink,bridges,total_ps,margin_ps,segment_budgets_ps,name):
    if not name.strip() or '\n' in name or '\r' in name:raise ValueError('Single-line path name is required')
    plan=series_path(context,source,sink,bridges)
    total,margin=_number(total_ps),_number(margin_ps)
    budgets=[_number(x) for x in segment_budgets_ps]
    if len(budgets)!=len(plan['segments']):raise ValueError('Supply one explicit PCB budget per path segment')
    used=sum(budgets)+margin+plan['component_delay_ps']
    if used>total+1e-9:raise ValueError('PCB + component + margin delay exceeds the total budget')
    rules=[]
    for i,(s,budget) in enumerate(zip(plan['segments'],budgets)):
        cond=function_test('A','fromTo',[s['from'],s['to']]).emit()
        rules.append(Rule(name+' / '+s['from']+' → '+s['to'],cond,'','error',
            [Constraint('length',{'max':f'{budget:.9g}ps'})],notes='CS-PATH '+name+'\nExplicit native-net segment; no through-component copper path is invented.'))
    plan.update(total_ps=total,margin_ps=margin,segment_budgets_ps=budgets,reserve_ps=total-used)
    return rules,plan


def stage_path(workspace,*args,**kwargs):
    rules,plan=compile_path(workspace.context,*args,**kwargs)
    name=kwargs.get('name',args[-1] if args else '')
    marker='CS-PATH '+name
    existing=[r for r in workspace.document.rules if marker in r.notes.splitlines()]
    previous=workspace.metadata.get('signal_paths',{}).get(name)
    if existing and (not previous or previous.get('rule_states')!=[r.state() for r in existing]):
        raise ValueError('Managed path rules changed manually; refusing replacement')
    if any(i.severity=='error' for i in lint(RuleDocument(rules=rules),workspace.floors)):
        raise ValueError('Path rules failed local validation')
    replace_generated(workspace.document,rules,marker)
    workspace.metadata.setdefault('signal_paths',{})[name]=dict(plan,rule_states=[r.state() for r in rules])
    return plan
