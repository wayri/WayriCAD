"""Deterministic constraint sets, timing budgets, matrix interchange and local review records.
No remote service, executable templates, SI solver, or implied manufacturing approval.
"""
from dataclasses import asdict
import copy, csv, datetime, hashlib, io, json, math, re
from .model import Constraint, Rule, RuleDocument, numeric, lint
from .catalog import CATALOG
from .expressions import function_test


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def rules_fingerprint(rules):
    return fingerprint([{'enabled':r.enabled,'text':r.emit_active()} for r in rules])


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# Saved parameter specifications are data, never scripts. {{...}} is separate from
# KiCad's ${...} variables so native variables are not accidentally substituted.
PARAMETER = re.compile(r'\{\{([A-Za-z_][A-Za-z_0-9]*)\}\}')
SEMVER = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')


def validate_profile(profile):
    if not isinstance(profile, dict) or profile.get('schema') != 1:
        raise ValueError('Unsupported profile schema; no silent migration')
    if not re.fullmatch(r'[A-Za-z][\w.\-]{0,127}', profile.get('id', '')):
        raise ValueError('Profile needs a stable identifier')
    if not SEMVER.fullmatch(profile.get('version', '')):
        raise ValueError('Profile version must be major.minor.patch')
    if not isinstance(profile.get('parameters', {}), dict):
        raise ValueError('Profile parameters must be a dictionary')
    if not isinstance(profile.get('rules', []), list) or not profile.get('rules'):
        raise ValueError('A profile must contain rule templates')
    for key, spec in profile.get('parameters', {}).items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key):
            raise ValueError('Invalid parameter name')
        if not isinstance(spec, dict) or spec.get('type') not in ('text', 'mm', 'ps', 'count', 'number', 'layer', 'deg'):
            raise ValueError('Unsupported parameter type: '+key)
    for rule in profile['rules']:
        if not isinstance(rule, dict) or not rule.get('constraints'):
            raise ValueError('Profile rule needs constraints')
        for c in rule['constraints']:
            if c.get('kind') not in CATALOG:
                raise ValueError('Unknown profile constraint; import as native rules to preserve extensions')
    if profile.get('floors') and not isinstance(profile['floors'], dict):
        raise ValueError('Manufacturing floors must be a dictionary')
    return profile


def validate_binding(value, spec):
    typ = spec['type']; value = str(value).strip()
    if not value:
        raise ValueError('All profile parameters require an explicit value')
    if len(value)>4096 or any(ch in value for ch in '\n\r\x00'):
        raise ValueError('Parameter must be a single bounded line')
    if typ in ('text', 'layer'):
        return value
    if typ == 'ps':
        v = numeric(value, 'ps')
        if v is None or v < 0: raise ValueError('Time must be a resolved nonnegative value')
        return f'{v:.12g}ps'
    if typ == 'deg':
        v=numeric(value,'deg')
        if v is None:raise ValueError('Angle must be resolved')
        return f'{v:.12g}deg'
    if typ == 'mm':
        v = numeric(value, 'mm')
        if v is None or v < 0: raise ValueError('Dimension must be a resolved nonnegative value')
        return f'{v:.12g}mm'
    v = numeric(value, 'count' if typ=='count' else 'ratio')
    if v is None or v<0: raise ValueError('Number must be nonnegative')
    return f'{v:.12g}'


def _substitute(text, values, expression=False):
    def repl(m):
        if m[1] not in values: raise ValueError('Unbound profile parameter: '+m[1])
        value=values[m[1]]
        # Condition placeholders are used *inside* native string literals. Escaping
        # prevents a reference/net-class name from injecting an expression clause.
        if expression: value=value.replace('\\','\\\\').replace("'", "\\'").replace('"','\\"')
        return value
    return PARAMETER.sub(repl, str(text))


def compile_profile(profile, bindings, instance):
    validate_profile(profile)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._\-/]{0,100}', instance):
        raise ValueError('Use a short, single-line instance name')
    params=profile.get('parameters', {})
    unknown=set(bindings)-set(params)
    if unknown: raise ValueError('Unknown parameters: '+', '.join(sorted(unknown)))
    values={k:validate_binding(bindings.get(k, s.get('default','')), s) for k,s in params.items()}
    result=[]
    for spec in profile['rules']:
        constraints=[]
        for c in spec['constraints']:
            constraints.append(Constraint(c['kind'], {k:_substitute(v,values) for k,v in c.get('values',{}).items()},
                _substitute(c.get('argument',''),values, expression=c['kind']=='assertion'),
                bool(c.get('within_diff_pairs',False))))
        result.append(Rule(instance+' / '+_substitute(spec.get('name','Rule'),values),
            _substitute(spec.get('condition',''), values, expression=True),
            _substitute(spec.get('layer',''),values),spec.get('severity','error'),constraints,
            notes=f'CS-SET {instance}\nProfile {profile["id"]} @ {profile["version"]}\n'+profile.get('description','')))
    errors=[i.message for i in lint(RuleDocument(rules=result)) if i.severity=='error']
    if errors: raise ValueError('\n'.join(errors))
    floors={k:numeric(_substitute(v, values),'mm') for k,v in profile.get('floors',{}).items()}
    from .model import FLOOR_KEYS
    if any(k not in set(FLOOR_KEYS.values()) for k in floors):
        raise ValueError('Unrecognized manufacturing floor key')
    if any(v is None or v<0 for v in floors.values()):
        raise ValueError('Manufacturing floors need nonnegative, resolved dimensions')
    return result, floors


def install_profile(workspace, profile, bindings, instance, apply_floors=False, approve_migration=False):
    """Transactional compile/replace. Manual edits to an owned block are protected."""
    result,floors=compile_profile(profile,bindings,instance)
    old=workspace.metadata.get('profile_instances',{}).get(instance)
    marker='CS-SET '+instance
    existing=[r for r in workspace.document.rules if marker in r.notes.splitlines()]
    if existing and not old:
        raise ValueError('This instance marker already exists without ownership metadata; choose a new instance name.')
    if old:
        if rules_fingerprint(existing)!=old.get('rules_hash'):
            raise ValueError('Managed rules were edited manually. Duplicate the instance or explicitly ungroup it before replacing.')
        if (old['profile_id'],old['version'],old.get('profile_hash'))!=(profile['id'],profile['version'],fingerprint(profile)) and not approve_migration:
            raise ValueError('Profile definition/version changed. Review the migration diff and explicitly approve this migration.')
    from .profiles import replace_generated
    replace_generated(workspace.document,result,marker)
    if floors and apply_floors:
        settings=workspace.project.setdefault('board',{}).setdefault('design_settings',{}).setdefault('rules',{})
        settings.update(floors)
    entry=dict(profile_id=profile['id'],version=profile['version'],profile_hash=fingerprint(profile),bindings=dict(bindings),
        rules_hash=rules_fingerprint(result),floors_applied=bool(floors and apply_floors))
    workspace.metadata.setdefault('profile_instances',{})[instance]=entry
    workspace.metadata.setdefault('profiles',{})[profile['id']+'@'+profile['version']]=copy.deepcopy(profile)
    return result


def capture_profile(rules, profile_id, name, version='1.0.0', parameter_names=(), floors=None):
    """Save selected native rules as a reusable, optionally parameterized set.
    Parameters are explicit tokens in rule text, never guessed from numeric values.
    """
    rs=[]
    for r in rules:
        if not r.enabled or r.extras or any(c.extras for c in r.constraints):
            raise ValueError('Capture enabled, fully modeled rules only. Native export preserves unsupported clauses.')
        rs.append(dict(name=r.name,condition=r.condition,layer=r.layer,severity=r.severity,
            constraints=[dict(kind=c.kind,values=c.values.copy(),argument=c.argument,within_diff_pairs=c.within_diff_pairs) for c in r.constraints]))
    p=dict(schema=1,id=profile_id,name=name,version=version,description='User-captured constraint set. Values require project-specific review.',
        parameters={n:dict(type='text',label=n) for n in parameter_names},rules=rs,floors=floors or {})
    return validate_profile(p)


def builtin_profiles():
    def p(pid,name,params,rules,description,floors=None):
        return dict(schema=1,id=pid,name=name,version='1.0.0',parameters=params,rules=rules,description=description,floors=floors or {})
    def par(typ,label):return dict(type=typ,label=label)
    def c(kind,**values):return dict(kind=kind,values=values)
    return [
        p('routing.netclass','Netclass routing',{'netclass':par('text','Netclass'),'width':par('mm','Track width'),'via':par('mm','Via diameter'),'drill':par('mm','Via drill')},
          [dict(name='Routing',condition="A.hasNetclass('{{netclass}}')",constraints=[c('track_width',min='{{width}}',opt='{{width}}'),c('via_diameter',min='{{via}}',opt='{{via}}'),c('hole_size',min='{{drill}}',opt='{{drill}}')])],
          'Reusable routing dimensions. No fabrication or impedance defaults are assumed.'),
        p('interface.differential','Differential-pair interface',{'pair':par('text','Pair base / pattern'),'width':par('mm','Track width'),'gap':par('mm','Coupled gap'),'skew':par('ps','Maximum skew (ps)'),'uncoupled':par('mm','Maximum uncoupled length')},
          [dict(name='Geometry',condition="A.inDiffPair('{{pair}}')",constraints=[c('track_width',opt='{{width}}'),c('diff_pair_gap',opt='{{gap}}'),c('diff_pair_uncoupled',max='{{uncoupled}}')]),
           dict(name='Time skew',condition="A.inDiffPair('{{pair}}')",constraints=[dict(kind='skew',values={'max':'{{skew}}'},within_diff_pairs=True)])],
          'Pair geometry plus native time-domain skew. Confirm the installed KiCad build and stackup. Opt values alone are not DRC limits.'),
        p('timing.fromto','From–to path delay',{'source':par('text','Source pad e.g. U1-A1'),'sink':par('text','Sink pad e.g. U2-B1'),'min':par('ps','Minimum delay'),'target':par('ps','Target delay'),'max':par('ps','Maximum delay'),'vias':par('count','Maximum vias')},
          [dict(name='Path budget',condition="A.fromTo('{{source}}', '{{sink}}')",constraints=[c('length',min='{{min}}',opt='{{target}}',max='{{max}}'),c('via_count',max='{{vias}}')])],
          'Native from-to path and timing intent. A series component is not assumed to be a same-net copper path.'),
        p('spacing.classes','Two-class spacing',{'class_a':par('text','Netclass A'),'class_b':par('text','Netclass B'),'clearance':par('mm','Minimum copper clearance')},
          [dict(name='Spacing',condition="A.hasNetclass('{{class_a}}') && B.hasNetclass('{{class_b}}')",constraints=[c('clearance',min='{{clearance}}')])],
          'Pairwise class exception. Later rules win; manufacturing floors remain separate.'),
        p('manufacturing.floor','Manufacturing floor + working defaults',{'floor_clearance':par('mm','Fabrication clearance floor'),'floor_width':par('mm','Fabrication width floor'),'working_clearance':par('mm','Normal clearance'),'working_width':par('mm','Normal track width')},
          [dict(name='Working defaults',constraints=[c('clearance',min='{{working_clearance}}'),c('track_width',min='{{working_width}}')])],
          'Explicit floor changes require a separate checkbox. Obtain these values from your approved fabrication process.',
          {'min_clearance':'{{floor_clearance}}','min_track_width':'{{floor_width}}'}),
        p('placement.classes','Component-class placement separation',{'class_a':par('text','Component class A'),'class_b':par('text','Component class B'),'distance':par('mm','Courtyard spacing')},
          [dict(name='Placement',condition="A.hasComponentClass('{{class_a}}') && B.hasComponentClass('{{class_b}}')",constraints=[c('courtyard_clearance',min='{{distance}}')])],
          'Courtyard spacing between component classes, not copper spacing inside a footprint.')
    ]


def matrix_to_csv(labels, cells):
    out=io.StringIO(newline='');w=csv.writer(out);w.writerow(['object']+list(labels))
    for i,label in enumerate(labels):w.writerow([label]+[cells.get((i,j),'') for j in range(len(labels))])
    return out.getvalue()


def matrix_from_csv(text):
    rows=list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))
    if len(rows)<2 or len(rows[0])<2:raise ValueError('CSV must include a header and at least one matrix row')
    labels=[s.strip() for s in rows[0][1:]];n=len(labels)
    if n>80 or not all(labels) or len(set(labels))!=n or len(rows)!=n+1:raise ValueError('Expected a square matrix with 1–80 unique labels')
    cells={}
    for i,row in enumerate(rows[1:]):
        if len(row)!=n+1 or row[0].strip()!=labels[i]:raise ValueError('Row and column labels must be in the same order')
        for j,v in enumerate(row[1:]):
            v=v.strip()
            if v:
                val=numeric(v,'mm')
                if val is not None and val<0:raise ValueError('Spacing must be nonnegative')
            cells[i,j]=v
    for i in range(n):
        for j in range(i+1,n):
            a,b=cells[i,j],cells[j,i]
            if a and b and a!=b:
                av,bv=numeric(a),numeric(b)
                if av is None or bv is None or av!=bv:raise ValueError('Asymmetric matrix values or unequal unresolved variables')
            cells[i,j]=cells[j,i]=a or b
    return labels,cells


def timing_budget(total_ps, package_ps=0, connector_ps=0, margin_ps=0):
    """Subtract explicitly supplied non-PCB contributions. Does not solve interconnects."""
    vals=[float(v) for v in (total_ps,package_ps,connector_ps,margin_ps)]
    if any(not math.isfinite(v) or v<0 for v in vals):raise ValueError('Budget inputs must be finite and nonnegative')
    pcb=vals[0]-sum(vals[1:])
    if pcb<0:raise ValueError('Package, connector and margin exceed the total timing budget')
    return dict(total_ps=vals[0],package_ps=vals[1],connector_ps=vals[2],margin_ps=vals[3],pcb_ps=pcb,
        warning='Budget allocation only. No package extraction, field solving, automatic layer delay, or SI sign-off.')


def length_from_delay(delay_ps, effective_er):
    t=float(delay_ps);er=float(effective_er)
    if not math.isfinite(t) or t<0 or not math.isfinite(er) or er<1:raise ValueError('Need nonnegative delay and effective permittivity >= 1')
    return t*0.299792458/math.sqrt(er)


def stackup_layers(context):
    """Read physical stackup entries without pretending epsilon_r is epsilon_eff."""
    setup=context.root.first('setup') if context.root else None
    stack=setup.first('stackup') if setup else None
    if not stack:return []
    from .sexpr import scalar
    result=[]
    for node in stack.find('layer'):
        result.append(dict(name=scalar(node),type=scalar(node.first('type')),material=scalar(node.first('material')),
            thickness=scalar(node.first('thickness')),epsilon_r=scalar(node.first('epsilon_r')),loss_tangent=scalar(node.first('loss_tangent'))))
    return result


def review_digest(workspace):
    return fingerprint(dict(rules=workspace.document.emit(),board=workspace.board_text,project=workspace.project,
        guards=workspace.guards,profiles=workspace.metadata.get('profile_instances',{}),matrices=workspace.metadata.get('matrices',{})))


def record_review(workspace, author, rationale, status='reviewed'):
    if status not in ('draft','reviewed','approved','rejected'):raise ValueError('Unknown local review state')
    if not author.strip() or not rationale.strip():raise ValueError('Reviewer and rationale are required')
    if status=='approved' and any(i.severity=='error' for i in workspace.issues()):raise ValueError('Fix local errors before marking a local review approved')
    entry=dict(at=utcnow(),author=author.strip(),rationale=rationale.strip(),status=status,content_hash=review_digest(workspace),
        previous=fingerprint(workspace.metadata.get('reviews',[])[-1]) if workspace.metadata.get('reviews') else '')
    workspace.metadata.setdefault('reviews',[]).append(entry)
    return entry


def review_state(workspace):
    rows=workspace.metadata.get('reviews',[])
    if not rows:return 'unreviewed'
    return rows[-1]['status'] if rows[-1].get('content_hash')==review_digest(workspace) else 'stale — content changed'


_STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'")


def profile_slots(profile):
    """Discover explicit literal fields for a no-code parameterization dialog.
    Numeric fields, layer values and quoted condition literals are individually
    addressable. This does not guess interface membership or timing topology.
    """
    import ast
    validate_profile(profile);slots=[]
    for ri,r in enumerate(profile['rules']):
        for ci,c in enumerate(r['constraints']):
            spec=CATALOG[c['kind']]
            for key,value in c.get('values',{}).items():
                if '{{' in str(value):continue
                unit=spec.unit
                typ='ps' if unit=='length_or_time' and 'ps' in str(value) else 'mm' if unit=='length_or_time' else {'ratio':'number','count':'count','deg':'deg','mm':'mm'}.get(unit,'text')
                slots.append(dict(key=(ri,'value',ci,key),label=r.get('name','Rule')+' / '+c['kind']+' / '+key,value=str(value),type=typ))
        if r.get('layer') and '{{' not in r['layer']:
            slots.append(dict(key=(ri,'layer'),label=r.get('name','Rule')+' / layer',value=r['layer'],type='layer'))
        for si,m in enumerate(_STRING_LITERAL.finditer(r.get('condition',''))):
            if '{{' in m[0]:continue
            try:value=ast.literal_eval(m[0])
            except (ValueError,SyntaxError):continue
            slots.append(dict(key=(ri,'scope',si),label=r.get('name','Rule')+' / scope literal '+str(si+1),value=value,type='text'))
    return slots


def parameterize_profile(profile,selections,use_defaults=False):
    """Selections maps slot indices to {name,type}. Blank/unselected stays literal."""
    result=copy.deepcopy(profile);slots=profile_slots(profile);scope_changes={}
    for i,binding in selections.items():
        if not isinstance(i,int) or not 0<=i<len(slots):raise ValueError('Unknown parameterization slot')
        name=binding.get('name','').strip();typ=binding.get('type',slots[i]['type'])
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',name):raise ValueError('Parameter names need letters, numbers and underscores; start with a letter/underscore')
        slot=slots[i];key=slot['key'];ri=key[0]
        param=dict(type=typ,label=name.replace('_',' ').capitalize())
        if use_defaults:param['default']=slot['value']
        old=result.setdefault('parameters',{}).get(name)
        if old and (old['type']!=typ or use_defaults and old.get('default')!=slot['value']):raise ValueError('A shared parameter needs a consistent type and default')
        result['parameters'][name]=param
        token='{{'+name+'}}'
        if key[1]=='value':result['rules'][ri]['constraints'][key[2]]['values'][key[3]]=token
        elif key[1]=='layer':result['rules'][ri]['layer']=token
        else:scope_changes.setdefault(ri,{})[key[2]]=token
    for ri,changes in scope_changes.items():
        index=[-1]
        def replace(match):
            index[0]+=1
            return "'"+changes[index[0]]+"'" if index[0] in changes else match[0]
        result['rules'][ri]['condition']=_STRING_LITERAL.sub(replace,result['rules'][ri].get('condition',''))
    return validate_profile(result)
