"""Bounded, non-executable query language shared by GUI, CLI and bulk plans.

Grammar: OR < AND (also implicit) < NOT, with parentheses. Predicates use
field : contains, = exact, != not-equal, ~ glob (* and ?), < <= > >= decimal.
Quote fields/values containing whitespace or operator characters. No eval,
SQL, arbitrary regex, Python expressions or network access is involved.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
from .native import BASE, natural

MAX_QUERY=4096
MAX_TOKENS=256
FLAGS={'fitted','fit','dnp','dni','not_fitted','excluded','on_board','variable','overridden','error','warning'}

@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int

def tokens(text):
    if not isinstance(text,str) or len(text)>MAX_QUERY:raise ValueError('Query must be text, at most 4,096 characters.')
    result=[];i=0
    while i<len(text):
        c=text[i]
        if c.isspace():i+=1;continue
        start=i
        if c in '\"\'':
            quote=c;i+=1;out=[]
            while i<len(text) and text[i]!=quote:
                if text[i]=='\\' and i+1<len(text) and text[i+1] in (quote,'\\'):
                    i+=1
                out.append(text[i]);i+=1
            if i==len(text):raise ValueError(f'Unclosed quote at character {start+1}.')
            i+=1;result.append(Token('word',''.join(out),start))
        elif c in '()':result.append(Token(c,c,i));i+=1
        elif c in ':=!~<>':
            i+=1
            if i<len(text) and text[i]=='=' and c in '!<>':i+=1
            op=text[start:i]
            if op=='!':raise ValueError(f'Use NOT or != at character {start+1}.')
            result.append(Token('op',op,start))
        else:
            while i<len(text) and not text[i].isspace() and text[i] not in '():=!~<>\"\'':i+=1
            word=text[start:i]
            result.append(Token(word.upper() if word.upper() in ('AND','OR','NOT') else 'word',word,start))
        if len(result)>MAX_TOKENS:raise ValueError('Query exceeds 256 tokens; split it into saved filters.')
    return result

class Parser:
    def __init__(self,text):self.ts=tokens(text);self.i=0;self.depth=0
    def peek(self):return self.ts[self.i].kind if self.i<len(self.ts) else 'end'
    def take(self,kind=None):
        if kind and self.peek()!=kind:raise ValueError('Expected '+kind+' near character '+str(self.ts[self.i].pos+1 if self.i<len(self.ts) else 1)+'.')
        t=self.ts[self.i];self.i+=1;return t.value
    def parse(self):
        if not self.ts:return ('all',)
        node=self.or_expr()
        if self.peek()!='end':raise ValueError('Unexpected token near character '+str(self.ts[self.i].pos+1)+'.')
        return node
    def or_expr(self):
        nodes=[self.and_expr()]
        while self.peek()=='OR':self.take();nodes.append(self.and_expr())
        return nodes[0] if len(nodes)==1 else ('or',nodes)
    def and_expr(self):
        nodes=[self.unary()]
        while self.peek() in ('AND','NOT','(','word'):
            if self.peek()=='AND':self.take()
            nodes.append(self.unary())
        return nodes[0] if len(nodes)==1 else ('and',nodes)
    def unary(self):
        self.depth+=1
        if self.depth>24:raise ValueError('Query nesting exceeds 24 levels.')
        try:
            if self.peek()=='NOT':self.take();return ('not',self.unary())
            if self.peek()=='(':
                self.take();node=self.or_expr();self.take(')');return node
            first=self.take('word')
            if self.peek()=='op':return ('test',first,self.take(),self.take('word'))
            return ('text',first)
        finally:self.depth-=1

def split_field(field):
    for prefix in ('raw.','resolved.'):
        if field.startswith(prefix):return prefix[:-1],field[len(prefix):]
    return 'resolved',field

def get_value(row,field):
    scope,name=split_field(field)
    if scope=='raw':return row['raw'].get(row.get('field_name_sources',{}).get(name,name),'')
    return row['fields'].get(name,'')

def decimal(text):
    text=str(text).strip()
    if len(text)>128 or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,4})?',text):return None
    try:
        d=Decimal(text)
        return d if d.is_finite() else None
    except InvalidOperation:return None

def glob(value,pattern):
    """Greedy wildcard match with bounded inputs. Only * and ? are special."""
    i=j=0;star=-1;mark=0
    while i<len(value):
        if j<len(pattern) and (pattern[j]=='?' or pattern[j]==value[i]):i+=1;j+=1
        elif j<len(pattern) and pattern[j]=='*':star=j;mark=i;j+=1
        elif star>=0:mark+=1;i=mark;j=star+1
        else:return False
    while j<len(pattern) and pattern[j]=='*':j+=1
    return j==len(pattern)

def compile_query(query,fields,case_sensitive=False,field_units=None):
    ast=Parser(query).parse();known=set(fields)
    fold=(lambda v:str(v)) if case_sensitive else (lambda v:str(v).casefold())
    def compile_node(node):
        kind=node[0]
        if kind=='all':return lambda r:True
        if kind=='and':
            ps=[compile_node(n) for n in node[1]];return lambda r:all(p(r) for p in ps)
        if kind=='or':
            ps=[compile_node(n) for n in node[1]];return lambda r:any(p(r) for p in ps)
        if kind=='not':
            p=compile_node(node[1]);return lambda r:not p(r)
        if kind=='text':
            target=fold(node[1]);return lambda r:any(target in fold(v) for v in r['fields'].values())
        _,field,op,target=node
        if field in ('has','missing'):
            if op!=':':raise ValueError('Use '+field+':"Field name".')
            if split_field(target)[1] not in known:raise ValueError('Unknown field: '+target)
            return lambda r:bool(str(get_value(r,target)).strip())==(field=='has')
        if field=='is':
            target=target.casefold()
            if op!=':' or target not in FLAGS:raise ValueError('Unknown is: predicate. Use '+', '.join(sorted(FLAGS))+'.')
            def flag(r):
                a=r['fields'].get('Assembly');f=r['flags']
                return {'fit':a=='FIT','fitted':a=='FIT','dnp':a=='DNP','dni':a=='DNI','not_fitted':a!='FIT',
                        'excluded':not f['in_bom'],'on_board':f['on_board'],
                        'variable':any('${' in str(k)+str(v) or '@{' in str(k)+str(v) for k,v in r['raw'].items()),
                        'overridden':any(str(v).startswith(('Workspace','Native:','Reviewed')) for v in r.get('origins',{}).values()),
                        'error':'error' in r.get('_severities',[]),'warning':'warning' in r.get('_severities',[])}[target]
            return flag
        if split_field(field)[1] not in known:raise ValueError('Unknown field: '+field+'. Field names are case-sensitive; quote names containing spaces.')
        if op in ('<','<=','>','>='):
            from . import measures
            unit=(field_units or {}).get(split_field(field)[1],'number')
            rhs=measures.literal(target,unit)
            if rhs.value is None:raise ValueError('Numeric comparison needs a finite decimal or explicitly supported unit: '+target+'; '+rhs.reason)
            effective=unit if unit!='number' else rhs.input_unit
            def number(r):
                lhs=measures.parse(get_value(r,field),effective,dimension=rhs.dimension)
                if lhs.value is None:return False
                return measures.compare(lhs.value,op,rhs.value)
            return number
        if op not in (':','=','!=','~'):raise ValueError('Unsupported query operator '+op)
        if op=='~' and len(target)>256:raise ValueError('Wildcard pattern exceeds 256 characters.')
        target=fold(target)
        def text(r):
            value=fold(get_value(r,field))
            if op==':':return target in value
            if op=='=':return target==value
            if op=='!=':return target!=value
            return glob(value,target)
        return text
    return compile_node(ast),ast

def select(ws,variant=BASE,query='',case_sensitive=False,rows=None,field_units=None):
    rows=ws.rows(variant) if rows is None else rows
    fields=set().union(*(set(r['fields'])|set(r['raw']) for r in rows)) if rows else set()
    fields.update(ws.state.get('aliases',{}))
    if field_units is None:
        from .analytics import units_for
        field_units=units_for(ws)
    predicate,ast=compile_query(query,fields,case_sensitive,field_units)
    if any(t.kind=='word' and t.value.casefold() in ('error','warning') for t in tokens(query)):
        byref={r['ref']:r for r in rows}
        for r in rows:r['_severities']=set()
        for issue in ws.checks(variant,rows):
            ref=issue.get('ref',issue.get('reference',''))
            if ref in byref:byref[ref]['_severities'].add(issue['severity'])
    matches=[r for r in rows if predicate(r)]
    for r in rows:r.pop('_severities',None)
    return matches,ast

def run(ws,variant=BASE,query='',case_sensitive=False,include_rows=False,field_units=None):
    rows,ast=select(ws,variant,query,case_sensitive,field_units=field_units)
    facets={}
    for name in ('Assembly','Manufacturer','Footprint','Sheet'):
        count=Counter(str(r['fields'].get(name,'')) for r in rows)
        facets[name]={'values':[{'value':v,'count':c} for v,c in count.most_common(100)],'distinct':len(count),'truncated':len(count)>100}
    return {'schema':'wayricad-query-1','variant':variant,'revision':ws.revision,'query':query,'case_sensitive':case_sensitive,
            'matched':len(rows),'total':len(ws.project.components),'ids':[r['id'] for r in rows],
            'references':[r['ref'] for r in rows],'facets':facets,**({'rows':rows} if include_rows else {})}

def validate_filters(filters):
    if not isinstance(filters,dict) or len(filters)>100:raise ValueError('At most 100 named search filters are allowed.')
    for name,record in filters.items():
        if not isinstance(name,str) or not name.strip() or len(name)>100 or name in ('__proto__','constructor','prototype'):raise ValueError('Invalid saved-filter name.')
        if not isinstance(record,dict) or set(record)-{'query','case_sensitive','description'}:raise ValueError('Unknown saved-filter options.')
        Parser(record.get('query','')).parse()
        if not isinstance(record.get('case_sensitive',False),bool):raise ValueError('case_sensitive must be true or false.')
        if not isinstance(record.get('description',''),str) or len(record.get('description',''))>2000:raise ValueError('Filter description too long.')

def save_filter(ws,name,record=None,remove=False):
    filters=dict(ws.state.get('saved_filters',{}))
    if remove:
        if name not in filters:raise ValueError('Unknown filter.')
        del filters[name]
    else:filters[name]=record
    validate_filters(filters)
    ws.commit('Update saved search filters',lambda:ws.state.update(saved_filters=filters))
    return {'ok':True,'count':len(filters)}

def bundle(ws):return {'schema':'wayricad-filters-1','filters':ws.state.get('saved_filters',{})}

def import_filters(ws,payload,replace=False):
    if not isinstance(payload,dict) or set(payload)!={'schema','filters'} or payload['schema']!='wayricad-filters-1':raise ValueError('Expected a wayricad-filters-1 JSON bundle.')
    validate_filters(payload['filters']);current=dict(ws.state.get('saved_filters',{}));collisions=set(current)&set(payload['filters'])
    if collisions and not replace:raise ValueError('Existing filter names: '+', '.join(sorted(collisions))+'. Enable Replace explicitly or rename the imported filters.')
    current.update(payload['filters']);validate_filters(current)
    ws.commit('Import saved filters',lambda:ws.state.update(saved_filters=current))
    return {'imported':len(payload['filters'])}
