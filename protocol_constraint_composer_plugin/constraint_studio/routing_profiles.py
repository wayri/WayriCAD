"""Persistent KiCad 10 layer geometry profiles; no running routing service.

Native schema: KiCad 10 common/project/tuning_profiles.cpp. Native dimensions
are integer nanometres (unlike netclass JSON, which uses millimetres).
"""
import copy
import hashlib
import json
import math
import fnmatch

from .expressions import function_test, property_test
from .model import Rule, Constraint, Issue
from .sexpr import scalar

KEY = 'tuning_profiles_impedance_geometric'
PROTOCOLS = ('CAN', 'DDR', 'Ethernet', 'USB', 'PCIe / SerDes', 'RS-485', 'RF', 'Custom')


def saved_classes(w, net):
    settings=w.project.get('net_settings',{})
    assigned=(settings.get('netclass_assignments') or {}).get(net,[])
    assigned=[assigned] if isinstance(assigned,str) else list(assigned or [])
    assigned += [r['netclass'] for r in (settings.get('netclass_patterns') or []) if
                 fnmatch.fnmatchcase(net,r.get('pattern',''))]
    return set(assigned) or {'Default'}


def selected_nets(w, data):
    nets = data.get('nets', [])
    if not isinstance(nets, list) or not nets or any(not isinstance(n,str) for n in nets):
        raise ValueError('Select one or more saved-board nets')
    if len(nets)>256 or len(nets)!=len(set(nets)): raise ValueError('Select unique nets, at most 256 per group')
    missing = set(nets)-set(w.context.nets)
    if missing: raise ValueError('Nets missing from the saved board: '+', '.join(sorted(missing)))
    if '' in nets: raise ValueError('Unconnected copper is not a named net')
    if data['type']=='differential':
        if len(nets)%2: raise ValueError('Select both nets of each differential pair')
        for net in nets:
            for positive,negative in (('_P','_N'),('+','-')):
                suffix = positive if net.endswith(positive) else negative if net.endswith(negative) else None
                if suffix:
                    mate=net[:-len(suffix)]+(negative if suffix==positive else positive)
                    if mate not in nets: raise ValueError('Differential pair selection is missing '+mate)
                    break
    for name, saved in w.metadata.get('routing_profiles', {}).items():
        if name==data['name']: continue
        if saved.get('scope','netclass')=='nets':
            overlap=set(nets)&set(saved['nets'])
            if overlap: raise ValueError('Nets already assigned to '+name+': '+', '.join(sorted(overlap)))
    for net in nets:
        membership=saved_classes(w,net)
        for c in w.project.get('net_settings',{}).get('classes',[]):
            if c.get('name') in membership and c.get('tuning_profile') not in (None,'',data['name']):
                raise ValueError(net+' already inherits tuning profile '+c['tuning_profile']+'; resolve that assignment first')
    return sorted(nets)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def stackup(w):
    setup = w.context.root.first('setup') if w.context.root else None
    node = setup.first('stackup') if setup else None
    rows = []
    for entry in node.find('layer') if node else []:
        rows.append(dict(name=scalar(entry), complex_dielectric=len(entry.find('thickness'))>1, **{key: scalar(entry.first(key))
                    for key in ('type', 'thickness', 'epsilon_r', 'material')}))
    return rows


def stack_hash(w):
    setup = w.context.root.first('setup') if w.context.root else None
    node = setup.first('stackup') if setup else None
    # Include sublayers, mask and material settings, not only displayed columns.
    return fingerprint([w.context.layers, w.board_text[node.start:node.end] if node else ''])


def number(value, label, allow_zero=False):
    try: value = float(value)
    except (TypeError, ValueError): raise ValueError(label + ' must be a number')
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise ValueError(label + ' must be finite and positive')
    return value


def cross_section(w, row):
    """Validate reference ordering, return physical dielectric spans without averaging Dk."""
    layers = stackup(w)
    copper = [r['name'] for r in layers if r['name'].endswith('.Cu')]
    signal, bottom, top = (str(row.get(k, '')) for k in ('signal_layer', 'bottom_reference_layer', 'top_reference_layer'))
    if signal not in copper or bottom not in copper or top and top not in copper:
        raise ValueError('Select signal and reference copper layers from the saved physical stackup')
    if signal == bottom or top and len({signal, bottom, top}) != 3:
        raise ValueError('Signal and reference layers must be different')
    si = copper.index(signal)
    if top and not copper.index(top) < si < copper.index(bottom):
        raise ValueError('Stripline requires the top reference above and bottom reference below the signal')
    if not top and si not in (0, len(copper)-1):
        raise ValueError('Internal signal layers require two reference planes')
    def span(ref):
        a, b = sorted([next(i for i, r in enumerate(layers) if r['name']==signal),
                       next(i for i, r in enumerate(layers) if r['name']==ref)])
        between = layers[a+1:b]
        if any(r.get('complex_dielectric') for r in between):
            raise ValueError('Composite dielectric sublayers require a verified external stackup model')
        if any(r['name'].endswith('.Cu') for r in between):
            raise ValueError('An intervening copper layer makes this reference model ambiguous')
        if not between: raise ValueError('No dielectric thickness between signal and reference')
        return between
    spans = [span(bottom)] + ([span(top)] if top else [])
    heights = [sum(number(r['thickness'], 'Dielectric thickness') for r in s) for s in spans]
    ers = [number(r['epsilon_r'], 'Dielectric permittivity') for s in spans for r in s]
    if any(er < 1 for er in ers): raise ValueError('Dielectric permittivity must be at least 1')
    trace = next(r for r in layers if r['name']==signal)
    return dict(kind='stripline' if top else 'microstrip', heights=heights, ers=ers,
                copper=number(trace['thickness'], 'Copper thickness'))


def estimate(w, data):
    """Fast screening estimate; fixed gap, solve width. Never a fabrication sign-off."""
    row = data['row']; section = cross_section(w, row)
    h = section['heights'][0]; er = section['ers'][0]; t = section['copper']
    if max(section['ers']) - min(section['ers']) > .01:
        raise ValueError('Mixed dielectrics require externally verified dimensions or a field solver')
    if section['kind']=='stripline' and abs(section['heights'][1]-h) > .01*h:
        raise ValueError('Asymmetric stripline requires externally verified dimensions or a field solver')
    target = number(data['target_impedance'], 'Target impedance')
    differential = data.get('type') == 'differential'
    gap = number(row.get('gap'), 'Fixed pair gap') if differential else 0
    if t >= h: raise ValueError('Copper thickness is outside this approximation')
    # IPC-style closed-form screening approximations. Height is dielectric face-to-face.
    if section['kind']=='microstrip':
        factor = 2*(1-.48*math.exp(-.96*gap/h)) if differential else 1
        width = (5.98*h/math.exp(target/factor*math.sqrt(er+1.41)/87)-t)/.8
    else:
        b = 2*h+t
        factor = 2*(1-.347*math.exp(-2.9*gap/b)) if differential else 1
        width = (1.9*b/math.exp(target/factor*math.sqrt(er)/60)-t)/.8
    if width <= 0 or not .1 <= width/h <= 3 or differential and not .1 <= gap/h <= 3:
        raise ValueError('Geometry is outside the screening model range; use verified external dimensions')
    return dict(width=round(width, 6), gap=gap, section=section,
                qualification='Approximate uniform-line geometry; excludes mask, roughness, weave, plane gaps and via discontinuities. Verify with your fabricator/field solver before staging.')


def native_profiles(w):
    return w.project.get('tuning_profiles', {}).get(KEY, [])


def status(w):
    managed = w.metadata.get('routing_profiles', {})
    return dict(stackup=stackup(w), profiles=copy.deepcopy(native_profiles(w)),
                managed=copy.deepcopy(managed), stack_hash=stack_hash(w),
                issues=[vars(i) for i in issues(w)])


def issues(w):
    result = []
    for name, saved in w.metadata.get('routing_profiles', {}).items():
        if saved['stack_hash'] != stack_hash(w):
            result.append(Issue('error', name, 'STALE ROUTING PROFILE: stackup changed; recalculate and review layer dimensions.'))
        if saved['native_hash'] != fingerprint([p for p in native_profiles(w) if p.get('profile_name')==name]):
            result.append(Issue('error', name, 'Managed native routing profile changed outside this editor.'))
        rules = [r.emit() for r in w.document.rules if r.name in saved['rule_names']]
        if fingerprint(rules) != saved['rules_hash']:
            result.append(Issue('error', name, 'Managed routing rules changed; resolve edits before regenerating.'))
        classes = w.project.get('net_settings', {}).get('classes', [])
        if saved.get('scope','netclass')=='nets':
            missing=set(saved['nets'])-set(w.context.nets)
            if missing: result.append(Issue('error',name,'Assigned nets disappeared or were renamed: '+', '.join(sorted(missing))))
        elif not any(c.get('name')==saved['netclass'] and c.get('tuning_profile')==name for c in classes):
            result.append(Issue('error', name, 'Routing profile is no longer assigned to its netclass.'))
    return result


def install(w, data):
    name = str(data.get('name', '')).strip()
    if not name or len(name)>120 or any(ord(c)<32 for c in name): raise ValueError('Enter a valid profile name')
    if data.get('type') not in ('single', 'differential'): raise ValueError('Choose single-ended or differential routing')
    if data.get('reviewed') is not True: raise ValueError('Review layer dimensions and reference-plane continuity before staging')
    if data.get('stack_hash') != stack_hash(w): raise ValueError('Stackup changed; reopen the profile')
    target = number(data.get('target_impedance'), 'Target impedance')
    tolerance = number(data.get('geometry_tolerance', 5), 'Geometry tolerance', True)
    if tolerance > 25: raise ValueError('Geometry tolerance must be 0–25 percent')
    classes = w.project.get('net_settings', {}).get('classes', [])
    scope=data.get('scope','netclass')
    if scope not in ('nets','netclass'): raise ValueError('Select nets or an existing netclass')
    if data.get('protocol','Custom') not in PROTOCOLS: raise ValueError('Unknown protocol family')
    nets=selected_nets(w,dict(data,name=name)) if scope=='nets' else []
    selected = [c for c in classes if c.get('name')==data.get('netclass')]
    if scope=='netclass' and len(selected)!=1: raise ValueError('Choose one existing netclass; assign its nets in Netclasses & settings')
    if scope=='netclass':
        for other,saved in w.metadata.get('routing_profiles',{}).items():
            if other!=name and saved.get('scope')=='nets' and any(data['netclass'] in saved_classes(w,n) for n in saved['nets']):
                raise ValueError('This netclass overlaps the selected nets of '+other)
    owned = w.metadata.get('routing_profiles', {}).get(name)
    existing = [p for p in native_profiles(w) if p.get('profile_name')==name]
    if existing and not owned: raise ValueError('This native profile is not managed by Studio; choose a new name')
    if owned:
        if owned.get('scope','netclass')!=scope: raise ValueError('Keep the original scope mode; create a new instance to change modes')
        if scope=='netclass' and owned['netclass'] != data['netclass']: raise ValueError('Keep the original netclass when updating this managed profile')
        if fingerprint(existing)!=owned['native_hash'] or fingerprint([r.emit() for r in w.document.rules if r.name in owned['rule_names']])!=owned['rules_hash']:
            raise ValueError('Managed profile or rules were edited independently; refusing to overwrite')
    if scope=='netclass' and selected[0].get('tuning_profile') not in (None, '', name):
        raise ValueError('This netclass already uses another tuning profile; resolve that assignment first')
    rows = data.get('rows', [])
    if not rows or len(rows)>32: raise ValueError('Select 1–32 permitted signal layers')
    differential = data['type']=='differential'; seen=set(); entries=[]; rules=[]
    condition = (' || '.join(property_test('A','NetName','==',net).emit() for net in nets)
                 if scope=='nets' else function_test('A', 'hasNetclass', [data['netclass']]).emit())
    def limits(value):
        return {k: f'{v:.6f}mm' for k,v in [('min',value*(1-tolerance/100)),('opt',value),('max',value*(1+tolerance/100))]}
    for row in rows:
        cross_section(w, row)
        layer = row['signal_layer']
        if layer in seen: raise ValueError('A signal layer may appear only once')
        seen.add(layer)
        width = number(row.get('width'), 'Trace width')
        gap = number(row.get('gap'), 'Pair gap') if differential else 0
        if max(width, gap)>100: raise ValueError('Routing dimensions exceed 100 mm')
        if width*(1-tolerance/100) < float(w.floors.get('min_track_width',0)):
            raise ValueError('Width tolerance falls below the board manufacturing minimum')
        if differential and gap*(1-tolerance/100) < float(w.floors.get('min_clearance',0)):
            raise ValueError('Gap tolerance falls below the board minimum clearance')
        entries.append(dict(signal_layer=layer, top_reference_layer=row.get('top_reference_layer') or 'UNDEFINED',
                            bottom_reference_layer=row['bottom_reference_layer'], width=round(width*1e6),
                            diff_pair_gap=round(gap*1e6), delay=0))
        constraints = [Constraint('track_width',limits(width))]
        # Native differential-gap DRC evaluates a single item; B may be absent.
        # Exact membership and complete recognized pairs are validated above.
        if differential: constraints.append(Constraint('diff_pair_gap', limits(gap)))
        rules.append(Rule(f'{name} / {layer}',condition,layer,'error',constraints,
                          notes='CS-ROUTING '+name+'\nLayer-specific routing geometry. Tolerance is dimensional, not impedance tolerance.'))
    if data.get('restrict_layers', True):
        for layer in w.context.layers:
            if layer.endswith('.Cu') and layer not in seen:
                rules.append(Rule(f'{name} / prohibit {layer}',condition,layer,'error',
                                  [Constraint('disallow',argument='track')],notes='CS-ROUTING '+name))
    old_names = set(owned['rule_names']) if owned else set()
    if any(r.name in {x.name for x in rules} and r.name not in old_names for r in w.document.rules):
        raise ValueError('A rule already uses one of this profile’s generated names')
    profile = dict(profile_name=name,type=1 if differential else 0,target_impedance=target,
                   enable_time_domain_tuning=False,layer_entries=entries,via_prop_delay=0,via_overrides=[])
    container = w.project.setdefault('tuning_profiles', {})
    container[KEY] = [p for p in native_profiles(w) if p.get('profile_name')!=name]+[profile]
    if scope=='netclass': selected[0]['tuning_profile'] = name
    # Above global defaults, below existing scoped exceptions. KiCad evaluates
    # later rules first. Never blindly append a broad rule over local neckdowns.
    kept = [r for r in w.document.rules if r.name not in old_names]
    insert = next((i for i,r in enumerate(kept) if r.condition.strip() and
                   any(c.kind in ('track_width','diff_pair_gap','disallow') for c in r.constraints)), len(kept))
    w.document.rules[:] = kept[:insert]+rules+kept[insert:]
    saved = copy.deepcopy(data); saved.pop('revision',None); saved.pop('reviewed',None)
    saved.update(name=name,scope=scope,protocol=data.get('protocol','Custom'))
    if scope=='nets': saved['nets']=nets
    saved.update(native_hash=fingerprint([profile]),rule_names=[r.name for r in rules],rules_hash=fingerprint([r.emit() for r in rules]))
    w.metadata.setdefault('routing_profiles', {})[name] = saved


def remove(w, name):
    saved=w.metadata.get('routing_profiles',{}).get(name)
    if not saved: raise ValueError('Only Studio-managed instances can be removed here')
    if fingerprint([p for p in native_profiles(w) if p.get('profile_name')==name])!=saved['native_hash'] or fingerprint([r.emit() for r in w.document.rules if r.name in saved['rule_names']])!=saved['rules_hash']:
        raise ValueError('Managed profile or rules changed independently; resolve edits before removing')
    w.project['tuning_profiles'][KEY]=[p for p in native_profiles(w) if p.get('profile_name')!=name]
    w.document.rules[:]=[r for r in w.document.rules if r.name not in saved['rule_names']]
    if saved.get('scope','netclass')=='netclass':
        for c in w.project.get('net_settings',{}).get('classes',[]):
            if c.get('name')==saved['netclass'] and c.get('tuning_profile')==name: c['tuning_profile']=''
    del w.metadata['routing_profiles'][name]
