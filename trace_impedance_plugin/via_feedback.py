"""Human-readable physical barrel evidence without filling unknown RF terms."""


def describe_via(section):
    evidence=section.get('via_geometry')
    if not evidence:
        return ''
    layers=evidence.get('physical_layers') or []
    length=evidence.get('physical_length_mm')
    physical=(' -> '.join((layers[0],layers[-1])) if layers else 'unknown span')
    if length is not None:
        physical+=' (%.4g mm)' % length
    parts=[str(evidence.get('via_type','via'))+' physical barrel: '+physical]
    active=evidence.get('connected_path_span')
    if active:
        parts.append('Selected route: %s -> %s (%.4g mm)' % (
            active['start_layer'],active['end_layer'],active['length_mm']))
    remaining=evidence.get('remaining_barrel')
    if remaining:
        parts.append('Residual barrel: '+', '.join('%s -> %s (%.4g mm)' % (
            row['start_layer'],row['end_layer'],row['length_mm']) for row in remaining))
        parts.append('Open stub or connected branch not verified; stub C, resonance and input impedance unresolved')
    elif remaining is not None:
        parts.append('No residual barrel beyond selected route span')
    else:
        parts.append('Stubs not evaluated without a terminal-defined path')
    return '; '.join(parts)


def via_notes(result):
    return list(dict.fromkeys(text for section in result.segments
                             if (text:=describe_via(section))))
