"""Conservative same-side 2D footprint envelope screen, never a solid-fit pass."""
import math
from .findings import candidate_pairs, finding
from .proximity import PairMeasurements, envelope_measure, nearest_parts


def screen(board, config):
    bodies, issues = [], []
    missing = ['2D screening only: component heights, exact solids, enclosure fit and assembly access are unchecked.']
    for c in board['components']:
        if c['dnp'] and not config['include_dnp']:
            continue
        x0,y0,x1,y1 = c['bounds_2d']
        if not all(math.isfinite(x) for x in (x0,y0,x1,y1)) or x1 <= x0 or y1 <= y0:
            missing.append(c['ref'] + ': missing or degenerate footprint envelope')
            continue
        # KiCad board coordinates invert Y relative to exported STEP scenes.
        y0,y1 = -y1,-y0
        z = board['thickness'] if c['side']=='top' else 0
        bounds = [x0,y0,z,x1,y1,z]
        bodies.append(dict(ref=c['ref'], kind='component', side=c['side'], bounds=bounds,
                           mesh=dict(vertices=[[x0,y0,z],[x1,y0,z],[x1,y1,z],[x0,y1,z]], faces=[[0,1,2],[0,2,3]])))
    cache = PairMeasurements(envelope_measure)
    for a,b in candidate_pairs(bodies, max(config['xy_clearance_mm'],config.get('proximity_warning_mm',0))):
        if a['side'] != b['side']:
            continue
        measurement = cache.get(a, b)
        distance = measurement['distance_mm']
        if distance < config['xy_clearance_mm'] or distance == 0:
            issues.append(finding('screen.footprint_envelope', [a['ref'],b['ref']],
                'Same-side footprint envelopes overlap or are close',
                'Inspect placement and courtyard; bounding boxes can overlap without physical interference. Use exact 3D mode for solid fit.',
                evidence='2D bounding-box screen', measured=distance, limit=config['xy_clearance_mm'], unit='mm', severity='warning',
                points=[measurement['points']]))
        elif config.get('proximity_warning_mm',0)>0 and distance<config['proximity_warning_mm']-1e-7:
            issues.append(finding('screen.proximity_warning',[a['ref'],b['ref']],
                'Footprint envelopes are inside the proximity warning distance',
                'Inspect the actual courtyard and model spacing; use Exact 3D for physical gaps.',
                evidence='2D bounding-box screen',measured=distance,limit=config['proximity_warning_mm'],
                unit='mm',severity='warning',points=[measurement['points']]))
    proximity = nearest_parts(bodies, cache, same_side=True)
    return dict(findings=issues,bodies=bodies,proximity=proximity,measurement_stats=cache.stats,
        board_outline=board.get('outline', dict(status='unavailable', polylines=[], bounds=None,
                                               reason='Saved Edge.Cuts outline was not extracted.', unit='mm')),
        coverage=dict(engine='KiCad footprint envelopes (2D)',
        expected_models=0,imported_models=0,components_with_solids=0,gaps=missing,
        screening=['same-side axis-aligned footprint envelopes; DNP filter applied']))
