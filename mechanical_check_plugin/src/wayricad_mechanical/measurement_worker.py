"""One bounded exact-distance request against immutable analysis BREP copies."""
import json
import sys
from pathlib import Path

from .proximity import exact_measure


def measure(request):
    # FreeCAD initializes its extension-module search path before Part is loaded.
    import FreeCAD
    import Part
    bodies = []
    for ref, filename in zip(request['refs'], request['files']):
        shape = Part.Shape()
        shape.read(filename)
        if shape.isNull() or not shape.isValid() or not shape.Solids:
            raise ValueError(ref + ': cached solid is invalid or unavailable; rerun analysis')
        bodies.append(dict(ref=ref, shape=shape))
    result = exact_measure(*bodies)
    if any(e != 'exact STEP surfaces' for e in request['evidence']):
        result['evidence'] = 'conservative hardware envelopes'
    return result


if __name__ == '__main__':
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    Path(sys.argv[2]).write_text(json.dumps(measure(request)), encoding='utf-8')
