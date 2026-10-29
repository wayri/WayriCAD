"""Advisory land-pattern families derived from pad geometry, never part names."""
import math
from .fanout_profiles import FANOUT_PATTERNS

FAMILIES = {
    'QFP/QFN / perimeter': ('Perimeter pitch expansion', 'Staggered rows',
        'Perimeter alternating inward / outward', 'Perimeter outward'),
    'BGA/LGA / grid': ('BGA/LGA grid outward', 'Dogbone outward', 'Dogbone inward',
        'Quadrant outward', 'Quadrant inward', 'Four-corner outward', 'Four-corner inward'),
    'Connector / SMT or plated THT': ('Connector edge',),
    'General / custom direction': ('Radial outward', '45-degree spread',
        'Custom-angle spread', 'Straight + angled escape'),
}


def styles_for(family, current):
    """Filtering never substitutes a reviewed or explicitly selected style."""
    choices = list(FANOUT_PATTERNS if family == 'All styles' else FAMILIES[family])
    if current not in choices:choices.append(current)
    return choices


def observed_family(footprint, api):
    pads = list(footprint.Pads())
    smd = [pad for pad in pads if pad.GetAttribute() == api.PAD_ATTRIB_SMD]
    through = [pad for pad in pads if pad.GetAttribute() == api.PAD_ATTRIB_PTH]
    if through:
        return 'Connector / SMT or plated THT', 'Mixed SMT/plated THT' if smd else 'Plated through-hole pads'
    if not smd:return None, 'No supported copper pads'
    rotation = -math.radians(float(footprint.GetOrientationDegrees()))
    def clusters(values):
        result=[]
        for value in sorted(values):
            if not result or value-result[-1]>2:result.append(value)
        return result
    positions=[pad.GetPosition() for pad in smd]
    xs=clusters([v.x*math.cos(rotation)+v.y*math.sin(rotation) for v in positions])
    ys=clusters([-v.x*math.sin(rotation)+v.y*math.cos(rotation) for v in positions])
    if len(xs)>=3 and len(ys)>=3 and len(xs)*len(ys)==len(smd):
        return 'BGA/LGA / grid', f'{len(xs)} × {len(ys)} populated pad grid'
    from .perimeter_escape import bank, _basis
    perimeter=[pad for pad in smd if _basis(footprint,pad) is not None]
    try:
        if len(perimeter)<2:raise ValueError()
        for pad in perimeter:bank(footprint,pad,api)
    except ValueError:
        return None, 'Multiple rows or irregular pad geometry; inspect grid/custom styles'
    center = len(smd)-len(perimeter)
    return 'QFP/QFN / perimeter', 'Aligned perimeter banks'+(' + center/exposed pads' if center else '')


def guidance(footprint, api, pattern):
    if footprint is None:return 'Select a component to see its observed pad layout. Family filtering preserves the current style.'
    try:family,description=observed_family(footprint,api)
    except (ValueError,AttributeError):family,description=None,'Pad layout could not be classified'
    note=f'{footprint.GetReference()}: {description}. '
    if family:
        note+='Suggested family: '+family+'. '
        if pattern != 'Via-in-pad' and pattern not in FAMILIES[family]:
            note+='Current style is outside this family; check its supported pad layout before Preview. '
    if pattern == 'Via-in-pad':note+='Via-in-pad uses individual SMD pad/via checks. '
    return note+'Geometry guidance only; Preview checks each pad and reports unsupported or blocked escapes.'
