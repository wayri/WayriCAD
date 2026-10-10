"""Reviewed 1D lead/solder paths; dimensions and properties are never inferred.

Pad copper belongs to the board mesh. These paths begin at its declared face
and end at a declared package node. Geometry factors integrate dz/A(z), in
1/m; multiplying by resistivity or dividing by conductivity gives ohm or K/W.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


def _number(raw, label, *, positive=True):
    try:
        if isinstance(raw, bool):
            raise ValueError()
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(label + ' must be a finite number.') from None
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(label + (' must be positive and finite.' if positive else ' must be nonnegative and finite.'))
    return value


def _text(raw, label):
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 256:
        raise ValueError(label + ' must be nonempty text (at most 256 characters).')
    return raw.strip()


def _sum(values, label):
    try:
        result = math.fsum(values)
    except OverflowError:
        raise ValueError(label + ': sum exceeds the finite numerical range.') from None
    if not math.isfinite(result):
        raise ValueError(label + ': sum exceeds the finite numerical range.')
    return result


def normalize_paths(raw, *, physics):
    """Return canonical definitions and calculated series resistances.

Electrical paths require rho_ohm_m on every segment; thermal paths require
k_w_mk. Other-physics properties stay unknown unless every segment supplies
them. A spherical_ball is a symmetric *truncated* sphere with finite necks,
not a guessed ball shape inferred from a pad diameter.
"""
    if physics not in ('electrical', 'thermal'):
        raise ValueError('Choose electrical or thermal contact physics.')
    if not isinstance(raw, list) or len(raw) > 4096:
        raise ValueError('package_conduction must be a list of at most 4096 paths.')
    output = []
    identities = set()
    allowed = {'id', 'reference', 'pad_number', 'layer_id', 'pad_uuid', 'port',
               'segments', 'additional_electrical_ohm', 'additional_thermal_k_per_w', 'evidence'}
    for index, path in enumerate(raw):
        label = 'Contact ' + str(index+1)
        if not isinstance(path, Mapping) or set(path)-allowed:
            raise ValueError(label + ': unsupported contact fields.')
        definition = {key: _text(path.get(key), label+' '+key)
                      for key in ('id', 'reference', 'pad_number')}
        label = definition['id']
        if label in identities:
            raise ValueError(label + ': duplicate contact identity.')
        identities.add(label)
        layer = path.get('layer_id')
        if isinstance(layer, bool) or not isinstance(layer, int) or not 0 <= layer <= 127:
            raise ValueError(label + ': layer_id must be a saved copper layer integer.')
        definition['layer_id'] = layer
        for key in ('pad_uuid', 'port', 'evidence'):
            if key in path:
                definition[key] = _text(path[key], label+' '+key)
        segments = path.get('segments')
        if not isinstance(segments, list) or not 1 <= len(segments) <= 32:
            raise ValueError(label + ': enter 1 to 32 ordered material segments.')
        calculated = []
        definition['segments'] = []
        for segment_index, segment in enumerate(segments):
            name = label + ' segment ' + str(segment_index+1)
            if not isinstance(segment, Mapping):
                raise ValueError(name + ': enter explicit segment properties.')
            shape = segment.get('shape')
            dimensions = {'cylinder': ('length_mm', 'diameter_mm'),
                          'rectangular': ('length_mm', 'width_mm', 'thickness_mm'),
                          'spherical_ball': ('length_mm', 'diameter_mm')}
            if shape not in dimensions:
                raise ValueError(name + ': choose cylinder, rectangular or spherical_ball.')
            keys = {'shape', 'rho_ohm_m', 'k_w_mk', 'material', 'evidence'} | set(dimensions[shape])
            if set(segment)-keys:
                raise ValueError(name + ': unsupported segment fields.')
            clean = {'shape': shape}
            for key in dimensions[shape]:
                clean[key] = _number(segment.get(key), name+' '+key)
                if not 1e-9 <= clean[key] <= 1e6:
                    raise ValueError(name+': dimensions must be within [1e-9, 1e6] mm.')
            length = clean['length_mm']
            if shape == 'rectangular':
                area = clean['width_mm']*clean['thickness_mm']
                factor = 1000*length/area
                min_area = max_area = area
                volume = area*length
            else:
                diameter = clean['diameter_mm']
                radius = diameter/2
                max_area = math.pi*radius**2
                if shape == 'cylinder':
                    min_area = max_area
                    factor = 1000*length/max_area
                    volume = max_area*length
                else:
                    if length >= diameter:
                        raise ValueError(name + ': spherical ball height must be less than diameter to retain finite solder necks.')
                    factor = 2000*math.atanh(length/diameter)/(math.pi*radius)
                    min_area = math.pi*(radius-length/2)*(radius+length/2)
                    volume = math.pi*length*(radius**2-length**2/12)
            if any(not math.isfinite(value) or value <= 0
                   for value in (factor, min_area, max_area, volume)):
                raise ValueError(name + ': geometry exceeds the finite numerical range.')
            for key in ('rho_ohm_m', 'k_w_mk'):
                if key in segment:
                    clean[key] = _number(segment[key], name+' '+key)
            required = 'rho_ohm_m' if physics == 'electrical' else 'k_w_mk'
            if required not in clean:
                raise ValueError(name + ': enter explicit '+required+'.')
            for key in ('material', 'evidence'):
                if key in segment:
                    clean[key] = _text(segment[key], name+' '+key)
            electrical = factor*clean['rho_ohm_m'] if 'rho_ohm_m' in clean else None
            thermal = factor/clean['k_w_mk'] if 'k_w_mk' in clean else None
            if any(value is not None and (not math.isfinite(value) or value <= 0)
                   for value in (electrical, thermal)):
                raise ValueError(name + ': calculated resistance exceeds the finite numerical range.')
            definition['segments'].append(clean)
            calculated.append({'definition': clean, 'geometric_factor_per_m': factor,
                               'minimum_area_mm2': min_area, 'maximum_area_mm2': max_area,
                               'volume_mm3': volume, 'electrical_resistance_ohm': electrical,
                               'thermal_resistance_k_per_w': thermal})
        totals = {}
        for quantity, addition in (('electrical_resistance_ohm', 'additional_electrical_ohm'),
                                   ('thermal_resistance_k_per_w', 'additional_thermal_k_per_w')):
            extra = _number(path[addition], label+' '+addition, positive=False) if addition in path else 0
            if addition in path:
                definition[addition] = extra
            values = [segment[quantity] for segment in calculated]
            total = _sum([*values, extra], label) if all(value is not None for value in values) else None
            if total is not None and (not math.isfinite(total) or total <= 0):
                raise ValueError(label + ': calculated path resistance is not finite and positive.')
            totals[quantity] = total
        output.append({'definition': definition, 'segments': calculated,
                       'geometric_factor_per_m': _sum((row['geometric_factor_per_m'] for row in calculated), label),
                       **totals})
    return output
