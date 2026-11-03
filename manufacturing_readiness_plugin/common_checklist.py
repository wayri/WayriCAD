"""Engineering work items, separate from sourced manufacturer numerical limits."""
from .checklists import validate_profile


COMMON_CHECKS = (
    ('acute-copper', 'Acute copper angles, etching slivers and trace neck-downs', 'DFM'),
    ('routing-ends', 'Unconnected routing ends and unintended copper islands', 'DRC'),
    ('via-in-pad', 'Via-in-pad filling, capping and solder-wicking requirements', 'DFM'),
    ('drill-process', 'Finished versus tool drill sizes, plated slots and annular rings', 'DFM'),
    ('via-stack', 'Blind, buried, stacked microvia and backdrill process limits', 'DFM'),
    ('mask-bridges', 'Solder mask bridges and minimum remaining mask webs', 'DFM'),
    ('mask-openings', 'Solder mask openings exposing traces or unintended copper', 'DFM'),
    ('mask-expansion', 'Negative mask expansion, merged openings and via tenting', 'DFM'),
    ('silk-pads', 'Silkscreen overlap with pads and solder mask openings', 'DFM'),
    ('silk-holes', 'Silkscreen clearance to holes and board edges', 'DFM'),
    ('silk-size', 'Silkscreen text height, stroke width and polarity legibility', 'DFM'),
    ('component-clearance', 'Component and courtyard spacing for the assembly process', 'DFA'),
    ('package-pads', 'Package land patterns, solder-mask-defined pads and BGA pads', 'DFA'),
    ('paste-apertures', 'Stencil apertures, paste area/aspect ratios and thermal-pad coverage', 'DFA'),
    ('thermal-balance', 'Unequal thermal relief, solder balance and tombstoning risks', 'DFA'),
    ('component-height', 'Component height, placement-tool clearance and reflow shadowing', 'DFA'),
    ('polarity', 'Pin 1, polarity, rotation and side convention in assembly outputs', 'DFA'),
    ('population', 'BOM, DNP/variant population and placement-file agreement', 'DFA'),
    ('test-access', 'Test-point, programming, inspection and rework access', 'DFA'),
    ('fiducials', 'Global/local fiducial scheme and assembly-machine visibility', 'DFA'),
    ('panel-rails', 'Panel rails, tooling holes, edge clearances and clamping access', 'DFA'),
    ('depanelization', 'V-score, routed tabs and depanelization stress keepouts', 'DFM'),
    ('stackup', 'Quoted stackup, copper basis, materials and fabrication tolerances', 'DFM'),
)


def with_common_checks(profile):
    result = validate_profile(profile)
    identifiers = {rule['id'] for rule in result['rules']}
    for identifier, title, category in COMMON_CHECKS:
        identifier = 'engineering-' + identifier
        if identifier in identifiers: continue
        result['rules'].append(dict(id=identifier, title=title, category=category, backend='manual',
                                    constraint=None, unit=None, minimum=None, maximum=None, source_ids=[],
                                    notes='WayriCAD engineering checklist item, not a published vendor limit. '
                                          'Acceptance requirements depend on the selected fabrication/assembly process. '
                                          'Attach measurements or supplier evidence and explicitly evaluate this item; it is not automatically checked.'))
    return validate_profile(result)
