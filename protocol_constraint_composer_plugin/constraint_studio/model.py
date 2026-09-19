"""Non-destructive native rule document, typed constraints, and conservative lint."""
from dataclasses import dataclass, field, asdict
import ast, base64, copy, json, math, operator, re
from .catalog import CATALOG, SEVERITIES
from .sexpr import parse, quote, scalar, ParseError
from .expressions import parse_expression

@dataclass
class Constraint:
    kind: str
    values: dict = field(default_factory=dict)
    argument: str = ''
    within_diff_pairs: bool = False
    extras: list = field(default_factory=list)
    def emit(self):
        parts=['constraint',self.kind]
        if self.argument:
            parts.append(quote(self.argument) if self.kind=='assertion' else self.argument)
        parts.extend(f'({k} {v.strip()})' for k,v in self.values.items() if str(v).strip())
        if self.within_diff_pairs:parts.append('(within_diff_pairs)')
        parts.extend(self.extras)
        return '(' + ' '.join(parts) + ')'

@dataclass
class Rule:
    name: str
    condition: str = ''
    layer: str = ''
    severity: str = ''
    constraints: list = field(default_factory=list)
    enabled: bool = True
    notes: str = ''
    extras: list = field(default_factory=list)
    original: str = ''
    baseline: str = ''
    leading: str = '\n\n'
    def state(self):
        return json.dumps({k:v for k,v in asdict(self).items() if k not in ('original','baseline','leading')},sort_keys=True)
    def emit_active(self):
        if self.original and self.state()==self.baseline:
            return self.original
        lines=[f'(rule {quote(self.name)}']
        if self.severity:lines.append(f'  (severity {self.severity})')
        if self.layer and self.layer!='Any':
            layer_token=self.layer if self.layer in ('inner','outer') else quote(self.layer)
            lines.append(f'  (layer {layer_token})')
        if self.condition.strip():lines.append(f'  (condition {quote(self.condition.strip())})')
        if self.notes:
            lines.extend('  # '+line for line in self.notes.splitlines())
        lines.extend('  '+c.emit() for c in self.constraints)
        lines.extend('  '+x for x in self.extras)
        lines.append(')')
        return '\n'.join(lines)
    def emit(self):
        active=self.emit_active()
        if self.enabled:return active
        # Commenting out is real disabling; severity=ignore is NOT disabling.
        data=base64.b64encode(active.encode('utf-8')).decode('ascii')
        return '# CS-DISABLED '+data+'\n'+'\n'.join('# | '+x for x in active.splitlines())
    def clone(self):
        r=copy.deepcopy(self);r.name += ' (copy)';r.original='';r.baseline='';r.leading='\n\n'
        return r


def rule_from_node(text,node):
    if len(node.children)<2:raise ParseError('Rule has no name')
    r=Rule(node.children[1].value,original=text[node.start:node.end])
    for n in node.children[2:]:
        if not n.is_list:
            r.extras.append(text[n.start:n.end]);continue
        h=n.head()
        if h in ('condition','layer','severity'):
            # Duplicate clauses stay opaque rather than being silently discarded.
            if getattr(r,h):r.extras.append(text[n.start:n.end])
            else:setattr(r,h,scalar(n))
        elif h=='constraint':
            if len(n.children)<2:raise ParseError('Constraint has no type')
            c=Constraint(n.children[1].value)
            bare=[]
            for arg in n.children[2:]:
                if arg.is_list and arg.head() in ('min','opt','max'):
                    if arg.head() in c.values:c.extras.append(text[arg.start:arg.end])
                    else:c.values[arg.head()]=text[arg.children[0].end:arg.end-1].strip()
                elif arg.is_list and arg.head()=='within_diff_pairs':c.within_diff_pairs=True
                elif not arg.is_list:bare.append(arg.value if c.kind=='assertion' else text[arg.start:arg.end])
                else:c.extras.append(text[arg.start:arg.end])
            c.argument=' '.join(bare)
            r.constraints.append(c)
        else:r.extras.append(text[n.start:n.end])
    # Retain every in-rule comment on an edited rule (including unknown annotations).
    comments=[];q=None;esc=False
    for line in r.original.splitlines():
        for j,ch in enumerate(line):
            if q:
                if esc:esc=False
                elif ch=='\\':esc=True
                elif ch==q:q=None
            elif ch in "'\"":q=ch
            elif ch=='#':comments.append(line[j+1:].lstrip());break
    r.notes='\n'.join(comments)
    r.baseline=r.state()
    return r

@dataclass
class RuleDocument:
    prefix: str = '(version 1)'
    rules: list = field(default_factory=list)
    suffix: str = '\n'
    source: str = ''
    @classmethod
    def load(cls,text):
        # Decode only our own disabled blocks; generic comments remain untouched.
        disabled=[]
        pattern=re.compile(r'(?m)^# CS-DISABLED ([A-Za-z0-9+/=]+)\r?\n(?:# \| [^\n]*(?:\n|$))*')
        def decode(m):
            try:s=base64.b64decode(m.group(1),validate=True).decode('utf-8')
            except (ValueError,UnicodeError) as e:raise ParseError('Corrupt disabled-rule block') from e
            p=parse(s)
            if len(p)!=1 or p[0].head()!='rule':raise ParseError('Invalid disabled-rule block')
            token=f'__CS_DISABLED_{len(disabled)}__'
            disabled.append(s)
            return f'(cs_disabled {token})\n'
        expanded=pattern.sub(decode,text)
        roots=parse(expanded)
        versions=[n for n in roots if n.head()=='version']
        if len(versions)!=1 or scalar(versions[0])!='1':
            raise ParseError('Exactly one (version 1) header is required; other language versions are preserved externally, not edited.')
        if roots[0].head()!='version':raise ParseError('Version header must be first')
        records=[n for n in roots if n.head() in ('rule','cs_disabled')]
        d=cls(source=text)
        if not records:d.prefix=expanded;d.suffix='';return d
        d.prefix=expanded[:records[0].start]
        for i,n in enumerate(records):
            if n.head()=='cs_disabled':
                idx=int(scalar(n).replace('__CS_DISABLED_','').replace('__',''))
                s=disabled[idx];r=rule_from_node(s,parse(s)[0]);r.enabled=False;r.baseline=r.state()
            else:r=rule_from_node(expanded,n)
            r.leading='' if i==0 else expanded[records[i-1].end:n.start]
            d.rules.append(r)
        d.suffix=expanded[records[-1].end:]
        return d
    def emit(self):
        if not self.rules:return self.prefix+self.suffix
        prefix=self.prefix
        if prefix and not prefix[-1].isspace():prefix+='\n\n'
        return prefix + ''.join(r.leading+r.emit() for r in self.rules) + self.suffix
    def append(self,rule):
        rule.leading='\n\n' if self.rules else '\n'
        self.rules.append(rule)
    def move(self,index,delta):
        j=index+delta
        if 0<=j<len(self.rules):self.rules[index],self.rules[j]=self.rules[j],self.rules[index];return j
        return index

_BINARY={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
_UNARY={ast.UAdd:operator.pos,ast.USub:operator.neg}
_NUM=re.compile(r'(?<![\w.])((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(mm|mil|th|in|deg|rad|ps)\b')
def numeric(value,unit='mm'):
    """Evaluate simple numeric inputs only; unresolved variables return None, never execute."""
    s=str(value).strip()
    if '${' in s:return None
    if not s:return None
    time = bool(re.search(r'\bps\b|(?<=\d)ps\b', s))
    if unit=='length_or_time':unit='ps' if time else 'mm'
    if time and unit!='ps':raise ValueError('Time units are only valid for length/skew timing constraints')
    def cv(m):
        n=float(m.group(1));u=m.group(2)
        factor={'mm':1,'mil':.0254,'th':.0254,'in':25.4,'deg':1,'rad':180/math.pi,'ps':1}[u]
        if unit=='ps' and u!='ps':raise ValueError('Cannot mix time and physical length units')
        if (unit in ('mm',) and u in ('deg','rad')) or (unit=='deg' and u not in ('deg','rad')):
            raise ValueError('Mixed angle and length units')
        if unit in ('count','ratio'):
            raise ValueError('Count / ratio cannot carry a length or angle unit')
        return str(n*factor)
    s=_NUM.sub(cv,s)
    try:tree=ast.parse(s,mode='eval')
    except SyntaxError as e:raise ValueError('Use a number, mm/mil/in/deg units, or a simple arithmetic expression') from e
    def calc(n,depth=0):
        if depth>30:raise ValueError('Expression too complex')
        if isinstance(n,ast.Constant) and type(n.value) in (int,float):return n.value
        if isinstance(n,ast.UnaryOp) and type(n.op) in _UNARY:return _UNARY[type(n.op)](calc(n.operand,depth+1))
        if isinstance(n,ast.BinOp) and type(n.op) in _BINARY:return _BINARY[type(n.op)](calc(n.left,depth+1),calc(n.right,depth+1))
        raise ValueError('Only arithmetic is accepted; no executable code or function calls')
    try:v=float(calc(tree.body))
    except (ZeroDivisionError,OverflowError) as e:raise ValueError('Invalid numeric result') from e
    if not math.isfinite(v):raise ValueError('Value must be finite')
    if unit=='count' and (v<0 or not v.is_integer()):raise ValueError('Count must be a nonnegative integer')
    return v

@dataclass
class Issue:
    severity: str
    rule: str
    message: str

FLOOR_KEYS={'clearance':'min_clearance','track_width':'min_track_width','via_diameter':'min_via_diameter','hole_size':'min_through_hole_diameter','annular_width':'min_via_annular_width','hole_to_hole':'min_hole_to_hole','hole_clearance':'min_hole_clearance','edge_clearance':'min_copper_edge_clearance'}

def lint(doc,floors=None):
    issues=[];seen={};scopes={}
    floors=floors or {}
    for i,r in enumerate(doc.rules):
        def add(sev,msg):issues.append(Issue(sev,r.name,msg))
        if not r.enabled:continue
        if not r.name.strip():add('error','Rule name is empty')
        if r.name in seen:add('warning','Duplicate rule name; reports will be ambiguous')
        seen[r.name]=i
        if r.severity and r.severity not in SEVERITIES:add('error','Unknown severity')
        if r.severity=='ignore':add('warning','Ignore still overrides lower-priority matching rules. Disable to remove a rule from evaluation.')
        if not r.constraints:add('error','At least one constraint is required')
        try:parse_expression(r.condition)
        except ValueError as e:add('error',str(e))
        if re.search(r'\b(?:true|false)\b',r.condition) and not re.search(r"['\"].*(?:true|false).*['\"]",r.condition):
            add('warning','KiCad does not use true/false boolean literals; use the property or its negation')
        if any(x in r.condition for x in ['intersectsCourtyard','insideCourtyard','intersectsFrontCourtyard','intersectsBackCourtyard']):
            add('warning','Intersection matches the WHOLE crossing item; it is not strict courtyard containment. Split boundary segments or use an enclosedByArea rule.')
        if 'B.' in r.condition and any(c.kind in CATALOG and not CATALOG[c.kind].pair for c in r.constraints):
            add('warning','Object B may be undefined for single-item constraints. Split pair clearance and single-item width into separate rules.')
        for c in r.constraints:
            spec=CATALOG.get(c.kind)
            if not spec:add('warning',f'Unknown constraint {c.kind}: preserved, not semantically validated');continue
            if c.extras or r.extras:add('warning','Unrecognized clauses are preserved and require native KiCad syntax checking')
            if spec.fields and not any(str(x).strip() for x in c.values.values()):add('error',f'{c.kind}: at least one value is required')
            nums={}
            if c.kind in ('length','skew'):
                timed=[bool(re.search(r'(?:\d|\s|\.)ps\b',str(v))) for v in c.values.values() if str(v).strip()]
                if any(timed) and not all(timed):add('error',f'{c.kind}: do not mix length and time domains within one constraint')
            for field,value in c.values.items():
                try:
                    v=numeric(value,spec.unit);nums[field]=v
                    if v is None:add('info',f'{c.kind}.{field}: variable-dependent expression must be checked by KiCad')
                    if v is not None and v<0 and c.kind not in ('clearance','courtyard_clearance','edge_clearance','silk_clearance','solder_mask_expansion','solder_paste_abs_margin','solder_paste_rel_margin'):
                        add('error',f'{c.kind}.{field}: negative value is not appropriate')
                    elif v is not None and v<0 and 'clearance' in c.kind:
                        add('warning',f'{c.kind}: negative clearance intentionally permits overlap')
                except ValueError as e:add('error',f'{c.kind}.{field}: {e}')
            for a,b in [('min','opt'),('opt','max'),('min','max')]:
                if nums.get(a) is not None and nums.get(b) is not None and nums[a]>nums[b]:add('error',f'{c.kind}: {a} is greater than {b}')
            floor_key=FLOOR_KEYS.get(c.kind,'');level='error'
            if c.kind in ('hole_size','via_diameter'):
                # Standard via/drill and microvia floors are different. Recognize
                # only provable positive scopes; never pretend to evaluate geometry.
                def micro_scope(e):
                    if e.op=='leaf':return re.sub(r'\s+','',e.text) in ("A.isMicroVia()","A.Via_Type=='Micro'",'A.Via_Type=="Micro"')
                    if e.op=='and':return any(micro_scope(x) for x in e.children)
                    if e.op=='or':return bool(e.children) and all(micro_scope(x) for x in e.children)
                    return False
                try:micro=micro_scope(parse_expression(r.condition))
                except ValueError:micro=False
                if micro:floor_key='min_microvia_drill' if c.kind=='hole_size' else 'min_microvia_diameter'
                else:level='warning' # mixed scopes may include legitimate microvias
            floor=floors.get(floor_key)
            if isinstance(floor,(int,float)) and nums.get('min') is not None and nums['min']<floor:
                add(level,f'{c.kind}: requested {nums["min"]:g} is below board floor {floor:g} mm ({floor_key}). Review native applicability and fabrication limits; floors are never silently relaxed.')
            if c.kind=='disallow' and (not c.argument or any(x not in spec.choices for x in c.argument.split())):add('error','Choose one or more supported disallow object types')
            if c.kind in ('zone_connection','min_resolved_spokes') and c.argument not in spec.choices:add('error',f'{c.kind}: invalid selection')
            if c.kind=='assertion':
                if re.search(r'\b(?:B|AB)\.',c.argument):add('error','Object B / AB is not available in assertion expressions')
                if not c.argument.strip():add('error','Assertion expression is empty')
                else:
                    try:parse_expression(c.argument)
                    except ValueError as e:add('error',f'Assertion: {e}')
            if c.within_diff_pairs and c.kind!='skew':add('error','within_diff_pairs is only applicable to skew')
            key=(r.condition.strip(),r.layer,c.kind)
            if key in scopes:add('warning',f'{c.kind}: exact-scope overlap with earlier rule "{scopes[key]}"; this later rule has priority')
            scopes[key]=r.name
    return issues
