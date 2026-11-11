"""Negative native assembly evidence; absence is not assembly approval."""

# Enable only providers for present checklist items, in the private copy.
PROVIDERS = {
    'engineering-component-clearance': ('courtyards_overlap', 'missing_courtyard', 'malformed_courtyard'),
    'engineering-mask-bridges': ('solder_mask_bridge',),
    'engineering-silk-pads': ('silk_over_copper',),
    'engineering-silk-holes': ('silk_edge_clearance',),
    'engineering-routing-ends': ('unconnected_items', 'track_dangling', 'via_dangling'),
}

CORRECTIONS = {
    'track_width': 'Increase the affected width or select a supplier process that explicitly supports it. Recheck neck-downs and ordinary project DRC.',
    'clearance': 'Increase separation on the affected copper layers; inspect pad, zone and netclass clearances before rerunning.',
    'drill_out_of_range': 'Use a supported finished drill and verify tool allowance with the supplier. Do not shrink the annular ring to compensate.',
    'annular_width': 'Increase the copper land or reduce the drill only when the process and current requirements permit it.',
    'copper_edge_clearance': 'Move copper away from the finished routed edge, or obtain an explicit edge-plating/castellation exception.',
    'courtyards_overlap': 'Review body and assembly-tool clearance on the same side. Correct the footprint courtyard before spacing parts from it.',
    'missing_courtyard': 'Add an accurate courtyard or explicitly exempt the non-assembly item in KiCad; missing geometry cannot establish clearance.',
    'malformed_courtyard': 'Repair the courtyard into closed, non-self-intersecting outlines, then repeat native DRC.',
    'solder_mask_bridge': 'Review mask openings and supplier web limits; an intentional merged opening requires supplier confirmation.',
    'silk_over_copper': 'Move reference/polarity markings out of exposed copper while preserving assembly legibility.',
    'silk_edge_clearance': 'Move legends inside the finished outline and review routed-panel boundaries.',
    'unconnected_items': 'Complete the intended connection or explicitly document its intentional unconnected state.',
    'track_dangling': 'Remove the unintended stub or complete its connection. Check the actual net and layer before editing.',
    'via_dangling': 'Connect the via on its intended copper layers or remove it if unintended.',
}


def apply_assembly_findings(results, findings):
    """Attach observed failures; clean output leaves broad requirements UNKNOWN."""
    for result in results:
        matching = [row for row in findings if row.get('type') in PROVIDERS.get(result['rule_id'], ())]
        if not matching:
            continue
        items = [item for row in matching for item in row.get('items', [])]
        result.update(status='FAIL', message=(f'{len(matching)} native finding(s) in this review area. '
                      'Partial negative evidence, not complete vendor/DFA coverage.'),
                      object_ids=list(dict.fromkeys(item['uuid'] for item in items if item.get('uuid'))))
    return results


def corrective_action(finding):
    return CORRECTIONS.get(finding.get('type'),
        'Inspect the highlighted native finding and its saved project rule. Correct the design or attach a justified, source-bound review exception, then rerun.')
