"""Explicitly grouped boolean expressions; KiCad uses equal AND/OR precedence.
No Python eval, no LLM and no approximation of geometry.
"""
from dataclasses import dataclass, field
import re
from .sexpr import expression_quote

@dataclass
class Expr:
    op: str = 'leaf'
    text: str = ''
    children: list = field(default_factory=list)
    def emit(self):
        if self.op=='leaf': return self.text.strip()
        if self.op=='not':
            if len(self.children)!=1 or not self.children[0].emit():raise ValueError('NOT needs one nonempty operand')
            return '!(' + self.children[0].emit() + ')'
        if self.op not in ('and','or'): raise ValueError('Unknown boolean operation')
        if not self.children or any(not c.emit() for c in self.children): raise ValueError('A boolean group needs nonempty conditions')
        sep=' && ' if self.op=='and' else ' || '
        return '(' + sep.join(c.emit() for c in self.children) + ')'
    def as_dict(self):
        return dict(op=self.op,text=self.text,children=[c.as_dict() for c in self.children])
    @classmethod
    def from_dict(cls,d):
        return cls(d['op'],d.get('text',''),[cls.from_dict(x) for x in d.get('children',[])])


def _top_operators(s):
    quote=None; escape=False; depth=0; out=[]; i=0
    while i<len(s):
        c=s[i]
        if quote:
            if escape: escape=False
            elif c=='\\': escape=True
            elif c==quote: quote=None
        elif c in "'\"": quote=c
        elif c=='(': depth+=1
        elif c==')':
            depth-=1
            if depth<0: raise ValueError('Unbalanced condition parentheses')
        elif depth==0 and s[i:i+2] in ('&&','||'):
            out.append((i,s[i:i+2])); i+=1
        i+=1
    if quote or depth: raise ValueError('Unbalanced condition string or parentheses')
    return out


def parse_expression(text,depth=0):
    if depth>100: raise ValueError('Expression nesting limit exceeded')
    s=text.strip()
    if not s: return Expr('leaf','')
    ops=_top_operators(s)
    if ops:
        # Rightmost split reconstructs left-to-right semantics without C/Python precedence.
        i,op=ops[-1]
        if not s[:i].strip() or not s[i+2:].strip(): raise ValueError('Missing boolean operand')
        return Expr('and' if op=='&&' else 'or',children=[parse_expression(s[:i],depth+1),parse_expression(s[i+2:],depth+1)])
    if s.startswith('(') and s.endswith(')'):
        # Only remove the pair when it encloses the WHOLE expression.
        depth2=0; q=None; esc=False; closes=None
        for i,c in enumerate(s):
            if q:
                if esc: esc=False
                elif c=='\\': esc=True
                elif c==q:q=None
            elif c in "'\"":q=c
            elif c=='(':depth2+=1
            elif c==')':
                depth2-=1
                if depth2==0: closes=i;break
        if closes==len(s)-1:return parse_expression(s[1:-1],depth+1)
    if s.startswith('!') and not s.startswith('!='):
        operand=parse_expression(s[1:],depth+1)
        if not operand.emit():raise ValueError('NOT needs a nonempty operand')
        return Expr('not',children=[operand])
    return Expr('leaf',s)


def property_test(obj, prop, operator, value='', value_type='string'):
    if obj not in ('A','B','AB'): raise ValueError('Select Object A, B or AB')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9%\-]*',prop): raise ValueError('Invalid property identifier')
    lhs=f'{obj}.{prop}'
    if operator=='is true':return Expr('leaf',lhs)
    if operator=='is false':return Expr('not',children=[Expr('leaf',lhs)])
    if operator not in ('==','!=','<','<=','>','>='):raise ValueError('Invalid comparison operator')
    if value_type=='string': rhs=expression_quote(value)
    elif value_type=='null':rhs='null'
    else:
        rhs=value.strip()
        if not rhs:raise ValueError('A comparison value is required')
        # Do not permit one value input to inject a second rule or boolean condition.
        if '\n' in rhs or '&&' in rhs or '||' in rhs or ';' in rhs:
            raise ValueError('Use the group builder for compound conditions')
    return Expr('leaf',f'{lhs} {operator} {rhs}')


def function_test(obj,name,args=(),negate=False,compare=None):
    from .catalog import FUNCTION_MAP
    if name not in FUNCTION_MAP:raise ValueError('Unknown function; use the advanced expression editor')
    _,n,selector,_=FUNCTION_MAP[name]
    if len(args)!=n:raise ValueError(f'{name} requires {n} argument(s)')
    if selector=='AB' and obj!='AB':raise ValueError(f'{name} requires the AB selector')
    if selector=='A/B' and obj not in ('A','B'):raise ValueError(f'{name} requires A or B')
    if any(not a.strip() for a in args):raise ValueError('Function arguments cannot be empty')
    text=f'{obj}.{name}(' + ', '.join(expression_quote(a) for a in args) + ')'
    if compare:
        op,value=compare
        if op not in ('==','!='):raise ValueError('Field comparison supports equality / inequality')
        text += f' {op} {expression_quote(value)}'
    e=Expr('leaf',text)
    return Expr('not',children=[e]) if negate else e


def both(function,target):
    return Expr('and',children=[function_test('A',function,[target]),function_test('B',function,[target])])
