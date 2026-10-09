"""Read-only viewport interaction state. Coordinates and lengths are in mm."""
import math


def valid_measurement(record):
    value = record.get('distance_mm')
    points = record.get('points')
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0
            and isinstance(points, (list, tuple)) and len(points) == 2
            and all(isinstance(p, (list, tuple)) and len(p) == 3 and all(isinstance(v, (int, float))
                    and not isinstance(v, bool) and math.isfinite(v) for v in p) for p in points))


def length_text(value):
    return f'{value:.6g} mm'


def measurement_text(record):
    if not record or not valid_measurement(record):
        return 'Distance unavailable: no measured geometry.'
    refs = ' ↔ '.join(record.get('refs', []))
    delta = [b-a for a, b in zip(*record['points'])]
    volume = record.get('overlap_volume_mm3', 0) or 0
    contact = ('' if record.get('type')=='point_ruler' else
               f' · overlap {volume:.6g} mm³' if volume > 0 else
               ' · contact / zero surface gap' if record['distance_mm'] == 0 else '')
    return (f"{refs}: {length_text(record['distance_mm'])}{contact} · {record.get('evidence', 'surface points')}"
            f" · ΔX {delta[0]:.6g}, ΔY {delta[1]:.6g}, ΔZ {delta[2]:.6g} mm")


class InspectionState:
    def __init__(self, report=None):
        self.mode = 'select'
        self.reset(report or {})

    def reset(self, report):
        self.report = report
        self.pair = []
        self.point_start = None
        self.rulers = []
        self.active = None
        self.nearest = {}
        self.pairs = {}
        for record in [*report.get('proximity', []), *report.get('measurements', [])]:
            self.register(record)
        self.rulers = [record for record in [*report.get('measurements', []), *report.get('point_rulers', [])]
                       if valid_measurement(record)][-20:]
        self.active = self.rulers[-1] if self.rulers else None

    def register(self, record):
        if not valid_measurement(record):
            return False
        refs = record.get('refs', [])
        if len(refs) == 2 and refs[0] != refs[1] and record.get('type') != 'point_ruler':
            self.pairs[frozenset(refs)] = record
        # Older records without this field are not evidence of a nearest part.
        for ref in ([] if record.get('type')=='point_ruler' else record.get('nearest_for', [])):
            previous = self.nearest.get(ref)
            if ref in refs and (previous is None or record['distance_mm'] < previous['distance_mm']):
                self.nearest[ref] = record
        return True

    def set_mode(self, mode):
        if mode not in ('select', 'parts', 'points'):
            raise ValueError('Choose select, parts or points mode')
        self.mode = mode
        self.pair = []
        self.point_start = None

    def click(self, hit):
        if not hit:
            return None
        if self.mode == 'parts':
            ref = hit['reference']
            if len(self.pair) == 2:
                self.pair = []
            if not self.pair or ref != self.pair[0]:
                self.pair.append(ref)
            return tuple(self.pair) if len(self.pair) == 2 else None
        if self.mode == 'points':
            point = list(hit['position'])
            if self.point_start is None:
                self.point_start = (hit['reference'], point)
                return None
            first_ref, first = self.point_start
            record = dict(refs=[first_ref, hit['reference']], points=[first, point],
                          distance_mm=math.dist(first, point), unit='mm', evidence='picked surface points',
                          type='point_ruler')
            self.point_start = None
            self.set_measurement(record)
            return record
        return None

    def set_measurement(self, record):
        if not self.register(record):
            raise ValueError('Measurement needs a finite distance and two finite witness points')
        self.active = record
        self.rulers.append(record)
        # Keep a bounded visible history while exports retain the measured evidence.
        self.rulers = self.rulers[-20:]

    def clear(self):
        self.rulers.clear()
        self.active = None
        self.pair = []
        self.point_start = None
