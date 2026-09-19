"""Visual-workflow compilers. Blank means inherit, never an implicit zero."""
import copy
from .model import Rule, Constraint, numeric
from .expressions import Expr, function_test, property_test


def bga_rules(reference,clearance,width='',via_diameter='',hole_size='',mode='area',area='',layer='F.Cu',name=None):
    if not reference.strip():raise ValueError('Choose a footprint')
    if not str(clearance).strip():raise ValueError('Clearance is required')
    if mode=='area':
        if not area.strip():raise ValueError('Choose/create a named rule area')
        fn='enclosedByArea';target=area
    elif mode=='intersection':fn='intersectsCourtyard';target=reference
    elif mode=='pads':fn='memberOfFootprint';target=reference
    else:raise ValueError('Unknown component scope')
    a=function_test('A',fn,[target]);b=function_test('B',fn,[target])
    pair=Expr('and',children=[a,b]).emit()
    base=name or f'{reference} escape'
    note='CS-PROFILE BGA; '+('STRICT whole-object containment. Crossing segments are NOT relaxed.' if mode=='area' else 'Whole-item intersection/membership. This is NOT strict geometric courtyard containment.')
    result=[Rule(base+' / clearance',pair,layer,'error',[Constraint('clearance',{'min':clearance})],notes=note)]
    singles=[]
    for kind,value in [('track_width',width),('via_diameter',via_diameter),('hole_size',hole_size)]:
        if str(value).strip():singles.append(Constraint(kind,{'min':value,'opt':value}))
    if singles:result.append(Rule(base+' / routing',a.emit(),layer,'error',singles,notes=note))
    return result


def matrix_rules(labels,cells,kind='clearance',scope='netclass',layer='',group='Main',region=''):
    if kind not in ('clearance','physical_clearance','creepage','courtyard_clearance','hole_clearance','physical_hole_clearance','hole_to_hole','silk_clearance'):
        raise ValueError('This matrix needs a two-object spacing constraint')
    if len(set(labels))!=len(labels) or any(not x.strip() for x in labels):raise ValueError('Matrix labels must be unique and nonempty')
    result=[]
    def atom(obj,label):
        if scope=='netclass':return function_test(obj,'hasNetclass',[label])
        if scope=='component_class':return function_test(obj,'hasComponentClass',[label])
        if scope=='type':return property_test(obj,'Type','==',label)
        if scope=='net':return property_test(obj,'NetName','==',label)
        raise ValueError('Unknown matrix scope')
    for i,left in enumerate(labels):
        for j in range(i,len(labels)):
            right=labels[j];v=str(cells.get((i,j),'')).strip()
            other=str(cells.get((j,i),'')).strip()
            if i!=j and v and other and v!=other:raise ValueError(f'Asymmetric entries for {left} / {right}; copper spacing is symmetric')
            v=v or other
            if not v:continue
            numeric(v)
            parts=[atom('A',left),atom('B',right)]
            if region:parts.extend([function_test('A','enclosedByArea',[region]),function_test('B','enclosedByArea',[region])])
            expr=Expr('and',children=parts).emit()
            result.append(Rule(f'Matrix {group} / {left} ↔ {right}',expr,layer,'error',[Constraint(kind,{'min':v})],
                notes=f'CS-MATRIX {group}\nSymmetric pair; KiCad tests the A/B assignment both ways. Blank cells inherit.'))
    return result


def replace_generated(doc,rules,marker):
    """Replace one named generated block, preserving its relative location."""
    positions=[i for i,r in enumerate(doc.rules) if marker in r.notes.splitlines()]
    if positions:
        insert=min(positions)
        doc.rules[:]=[r for i,r in enumerate(doc.rules) if i not in positions]
        doc.rules[insert:insert]=rules
    else:
        for r in rules:doc.append(r)


def profile_rules(kind,target,values,layer=''):
    """Values intentionally supplied by the user; no fabricated sign-off defaults."""
    if kind=='Board default':
        return [Rule('Board working defaults','',layer,'error',[Constraint(k,{'min':v}) for k,v in values.items() if v.strip()])]
    if kind=='Netclass routing':
        cond=function_test('A','hasNetclass',[target]).emit()
        return [Rule(target+' routing',cond,layer,'error',[Constraint(k,{'min':v,'opt':v}) for k,v in values.items() if v.strip()])]
    if kind=='Differential pair':
        cond=function_test('A','inDiffPair',[target]).emit()
        specs=[]
        for k,v in values.items():
            if v.strip():specs.append(Constraint(k,{'max' if k in ('diff_pair_uncoupled','skew') else 'opt':v},within_diff_pairs=k=='skew'))
        return [Rule(target+' differential pair',cond,layer,'error',specs)]
    if kind=='Keepout area':
        return [Rule(target+' keepout',function_test('A','intersectsArea',[target]).emit(),layer,'error',
            [Constraint('disallow',argument=values.get('disallow','track via'))])]
    if kind=='Matched length group':
        cond=function_test('A','memberOfGroup',[target]).emit()
        return [Rule(target+' length budget',cond,layer,'error',[Constraint(k,{'max' if k=='skew' else 'opt':v}) for k,v in values.items() if v.strip()])]
    raise ValueError('Unknown profile')
