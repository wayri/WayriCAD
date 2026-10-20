"""Explicit ideal equipotential pad units for fixed-current copper solves."""


def pad_names(spec, singular='terminal', plural='terminals'):
    if singular in spec and plural in spec:
        raise ValueError('Choose '+singular+' or '+plural+', not both.')
    values=spec.get(plural,[spec.get(singular)])
    if (not isinstance(values,list) or not 1<=len(values)<=1024 or
            any(not isinstance(v,str) or not v.strip() for v in values)):
        raise ValueError(plural+' requires 1 to 1,024 explicit pad labels or UUIDs.')
    if len(set(values))!=len(values):
        raise ValueError('Repeated pad in '+plural+'.')
    return list(values)


def source_names(request):
    return pad_names(request,'source_terminal','source_terminals')


def resolve_units(request,geometry,mesh,specs):
    """Resolve labels/UUIDs on the selected net; reject aliases and node overlap."""
    occupied=set();occupied_nodes=set()
    def unit(names):
        rows=[];nodes=[];local_ids=set()
        for chosen in names:
            matches=[t for t in geometry['terminals'] if t['id']==chosen or t['label']==chosen]
            if len(matches)!=1:
                raise ValueError('Select one unambiguous pad on net '+str(request['net'])+': '+chosen)
            row=matches[0];indices=mesh['terminal_nodes'].get(row['id'])
            if row.get('net',request['net'])!=request['net']:
                raise ValueError('Every pad in a terminal unit must belong to the selected net.')
            if not indices:raise ValueError('Selected pad has no mesh vertices: '+chosen)
            if row['id'] in occupied or row['id'] in local_ids or occupied_nodes.intersection(indices):
                raise ValueError('Repeated sink identity or terminal pads overlap across source/load units: '+chosen)
            local_ids.add(row['id'])
            rows.append(row);nodes.extend(indices)
        occupied.update(local_ids);occupied_nodes.update(nodes)
        return rows,sorted(set(nodes))
    source_rows,source_nodes=unit(source_names(request))
    sinks=[];evidence=[]
    for spec in specs:
        rows,indices=unit(pad_names(spec))
        identifier=spec.get('id') or rows[0]['id']
        sinks.append({**spec,'nodes':indices,'id':identifier,
                      'label':spec.get('label') or ' + '.join(r['label'] for r in rows)})
        evidence.append({'id':identifier,'terminals':[r['id'] for r in rows],
                         'labels':[r['label'] for r in rows],'current_A':spec['current_A']})
    return source_rows,source_nodes,sinks,{'source_terminals':[r['id'] for r in source_rows],
        'source_labels':[r['label'] for r in source_rows],'loads':evidence,
        'assumption':'Pads within each explicitly selected unit are ideal equipotential contacts. '
                     'The FEM distributes the total unit current by copper conductance; no equal pad-current split is assumed.'}
