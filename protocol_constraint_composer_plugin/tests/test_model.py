import copy, math, pytest
from protocol_constraint_composer_plugin.constraint_studio.catalog import SPECS,CATALOG,FUNCTIONS,PROPERTY_TYPES
from protocol_constraint_composer_plugin.constraint_studio.sexpr import parse,quote,ParseError
from protocol_constraint_composer_plugin.constraint_studio.model import RuleDocument,Rule,Constraint,numeric,lint
from protocol_constraint_composer_plugin.constraint_studio.expressions import Expr,parse_expression,property_test,function_test
from conftest import RULES

def test_vocabulary_size():
    assert len(SPECS)==34
    assert len(CATALOG)==34
    assert len(FUNCTIONS)==27
    assert len(PROPERTY_TYPES)>=90

@pytest.mark.parametrize('s',[RULES,'(version 1)\n(rule "c" (condition "A.NetName == \'a#b\'") (constraint clearance (min 0.2mm)))\n','\ufeff(version 1)\n(rule "x" (constraint assertion "A.Width > 1mm"))\n'])
def test_exact_roundtrip(s):assert RuleDocument.load(s).emit()==s

def test_unknown_preserved():
    s='(version 1)\n(rule "r" # note\n (condition "A.NetName == \'X\'") (mystery 42) (constraint future (k 4) 123))\n'
    d=RuleDocument.load(s);assert d.emit()==s
    d.rules[0].name='edited';out=d.emit();assert '(mystery 42)' in out and '(k 4)' in out and '# note' in out
    assert RuleDocument.load(out).rules[0].constraints[0].kind=='future'

def test_disable_is_comment_not_ignore():
    d=RuleDocument.load(RULES);d.rules[0].enabled=False;s=d.emit()
    assert len([r for r in parse(s) if r.head()=='rule'])==0
    reloaded=RuleDocument.load(s);assert not reloaded.rules[0].enabled
    reloaded.rules[0].enabled=True
    assert len([r for r in parse(reloaded.emit()) if r.head()=='rule'])==1
    assert 'severity ignore' not in reloaded.emit()

def test_disabled_stable_cycles():
    d=RuleDocument.load(RULES);d.rules[0].enabled=False;s=d.emit()
    for _ in range(10):s2=RuleDocument.load(s).emit();assert s2==s;s=s2

def test_move_semantics_and_comments():
    d=RuleDocument.load(RULES);d.append(Rule('Local',constraints=[Constraint('clearance',{'min':'0.1mm'})]))
    d.move(1,-1)
    out=RuleDocument.load(d.emit());assert [r.name for r in out.rules]==['Local','Board working defaults']
    assert 'Original project header' in out.emit() and 'Trailing project note' in out.emit()

@pytest.mark.parametrize('s',['(version 2)','(rule "r") (version 1)','(version 1)(version 1)','(version 1) (rule "r"','(version 1) )'])
def test_invalid_document(s):
    with pytest.raises(ValueError):RuleDocument.load(s)

@pytest.mark.parametrize('kind',list(CATALOG))
def test_all_constraint_roundtrips(kind):
    sp=CATALOG[kind];c=Constraint(kind,{k:'2' if sp.unit in ('count','ratio') else '0.2deg' if sp.unit=='deg' else '0.2mm' for k in sp.fields})
    if kind=='assertion':c.argument="A.Width > 0.1mm"
    if sp.choices:c.argument=sp.choices[0]
    if kind=='skew':c.within_diff_pairs=True
    d=RuleDocument(rules=[Rule('Test',constraints=[c])]);d2=RuleDocument.load(d.emit())
    assert d2.rules[0].constraints[0]==c
    assert not [i for i in lint(d) if i.severity=='error']

@pytest.mark.parametrize('value,unit,expected',[('4mil','mm',.1016),('1in','mm',25.4),('0.1mm + 4mil','mm',.2016),('180deg / 2','deg',90),('3','count',3),('-0.12','ratio',-.12),('.1mm','mm',.1),('1e-3mm','mm',.001)])
def test_units(value,unit,expected):assert numeric(value,unit)==pytest.approx(expected)

@pytest.mark.parametrize('value,unit',[('3.4','count'),('-1','count'),('2mm','ratio'),('2deg','mm'),('3mm','deg'),('1/0','mm'),('__import__("os").system("echo unsafe")','mm'),('2**1000','mm'),('1e999','mm')])
def test_unsafe_numeric(value,unit):
    with pytest.raises(ValueError):numeric(value,unit)

def test_variables_preserved():assert numeric('${CLEARANCE}') is None

def test_priority_overlap():
    d=RuleDocument(rules=[Rule('low',constraints=[Constraint('clearance',{'min':'.2mm'})]),Rule('high',constraints=[Constraint('clearance',{'min':'.3mm'})])])
    issues=lint(d);assert any('earlier rule "low"' in i.message and i.rule=='high' for i in issues)

def test_floor_violation():
    d=RuleDocument(rules=[Rule('BGA',constraints=[Constraint('clearance',{'min':'.1mm'})])]);assert any(i.severity=='error' and 'floor' in i.message for i in lint(d,{'min_clearance':.2}))

def test_min_max_order():
    d=RuleDocument(rules=[Rule('bad',constraints=[Constraint('track_width',{'min':'.3mm','opt':'.1mm','max':'.2mm'})])]);assert sum(i.severity=='error' for i in lint(d))>=2

def test_equal_precedence():
    s='A.Locked || A.Visible && A.Bold'
    assert parse_expression(s).emit()=='((A.Locked || A.Visible) && A.Bold)'

def test_grouping_kept():assert parse_expression('A.Locked || (A.Visible && A.Bold)').emit()=='(A.Locked || (A.Visible && A.Bold))'

def test_operator_in_string():assert parse_expression("A.NetName == 'a||b' && A.Type == 'Pad'").emit()=="(A.NetName == 'a||b' && A.Type == 'Pad')"

@pytest.mark.parametrize('s',['A.Locked &&','(A.Locked','A.Type == \'Pad','A.Locked || || A.Visible'])
def test_invalid_expression(s):
    with pytest.raises(ValueError):parse_expression(s)

def test_property_quote():
    e=property_test('A','NetName','==',"x'y")
    assert e.emit()=="A.NetName == 'x\\'y'"
    assert property_test('A','Locked','is false').emit()=='!(A.Locked)'

def test_documented_property_punctuation():
    assert property_test('A','Corner_Radius_%','>=','25','integer').emit()=='A.Corner_Radius_% >= 25'
    assert property_test('A','Single-sided','is true').emit()=='A.Single-sided'

@pytest.mark.parametrize('fn,arity,selector,help',FUNCTIONS)
def test_all_function_emit(fn,arity,selector,help):
    args=['test']*arity;obj='AB' if selector=='AB' else 'A';out=function_test(obj,fn,args).emit()
    assert out.startswith(obj+'.'+fn+'(')
    assert parse_expression(out).emit()==out

def test_wrong_ab():
    with pytest.raises(ValueError):function_test('A','isCoupledDiffPair',[])

def test_courtyard_warning():
    d=RuleDocument(rules=[Rule('c',"A.intersectsCourtyard('U1')",constraints=[Constraint('clearance',{'min':'.2mm'})])]);assert any('WHOLE' in i.message for i in lint(d))

def test_ignore_is_warned():
    d=RuleDocument(rules=[Rule('c',severity='ignore',constraints=[Constraint('via_dangling')])]);assert any('Ignore still' in i.message for i in lint(d))

def test_assertion_rejects_b():
    d=RuleDocument(rules=[Rule('assert',constraints=[Constraint('assertion',argument='A.Net != B.Net')])])
    assert any(x.severity=='error' and 'not available' in x.message for x in lint(d))

def test_not_requires_operand():
    with pytest.raises(ValueError):parse_expression('!')
    with pytest.raises(ValueError):Expr('not',children=[Expr()]).emit()

@pytest.mark.parametrize('layer',['inner','outer'])
def test_special_layer_not_quoted(layer):
    out=RuleDocument(rules=[Rule('x',layer=layer,constraints=[Constraint('clearance',{'min':'.2mm'})])]).emit()
    assert '(layer '+layer+')' in out

def test_microvia_floor_is_distinct():
    r=Rule('micro',"A.isMicroVia()",constraints=[Constraint('hole_size',{'min':'.1mm'}),Constraint('via_diameter',{'min':'.2mm'})])
    floor={'min_through_hole_diameter':.3,'min_via_diameter':.6,'min_microvia_drill':.1,'min_microvia_diameter':.2}
    assert not [x for x in lint(RuleDocument(rules=[r]),floor) if x.severity=='error']
    r.constraints[0].values['min']='.05mm'
    assert any(x.severity=='error' and 'min_microvia_drill' in x.message for x in lint(RuleDocument(rules=[r]),floor))

def test_crlf_roundtrip():
    text=RULES.replace('\n','\r\n');assert RuleDocument.load(text).emit()==text
