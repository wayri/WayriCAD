"""Versioned project settings. All dimensions are millimetres."""
import json
import math
from copy import deepcopy
from pathlib import Path

DEFAULTS = {
    "schema_version": 1,
    "project_name": "",
    "project_revision": "",
    "reviewer": "",
    "clearance_mm": 0.25,
    "xy_clearance_mm": 0.25,
    "z_clearance_mm": 0.5,
    "top_height_mm": 12.0,
    "bottom_height_mm": 3.0,
    "nozzle_radius_mm": 1.5,
    "nozzle_travel_mm": 15.0,
    "screw_clearance_mm": 0.5,
    "volume_tolerance_mm3": 0.0001,
    "include_dnp": False,
    "mounts": {},
    "height_zones": [],
    "keepouts": [],
    "enclosures": [],
    "waivers": {},
    "model_variables": {},
}


def validate(config):
    if not isinstance(config, dict):
        raise ValueError('Settings must be a JSON object')
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ValueError('Unknown settings: ' + ', '.join(sorted(unknown)))
    out = deepcopy(DEFAULTS)
    out.update(config)
    if out['schema_version'] != 1:
        raise ValueError('Unsupported settings schema')
    for key, value in out.items():
        if key.endswith('_mm') or key.endswith('_mm3'):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(key + ' must be a finite, non-negative number')
    if not isinstance(out['include_dnp'], bool):
        raise ValueError('include_dnp must be true or false')
    for key in ('project_name', 'project_revision', 'reviewer'):
        if not isinstance(out[key], str):
            raise ValueError(key + ' must be text')
    for key in ('mounts', 'waivers', 'model_variables'):
        if not isinstance(out[key], dict):
            raise ValueError(key + ' must be an object')
    for key in ('height_zones', 'keepouts', 'enclosures'):
        if not isinstance(out[key], list) or any(not isinstance(item,dict) for item in out[key]):
            raise ValueError(key + ' must be a list of objects')
    if any(not isinstance(k,str) or not isinstance(v,str) for k,v in out['model_variables'].items()):
        raise ValueError('Model variables must map text names to text paths')
    for ref, mount in out['mounts'].items():
        if not isinstance(mount, dict):
            raise ValueError(ref + ': hardware definition must be an object')
        allowed={'expected_plating','side','head_diameter_mm','head_height_mm','washer_diameter_mm','shaft_diameter_mm','tool_radius_mm'}
        if set(mount)-allowed:
            raise ValueError(ref + ': unknown hardware setting')
        if mount.get('expected_plating') not in ('PTH', 'NPTH', 'either'):
            raise ValueError(ref + ': choose PTH, NPTH or either')
        if mount.get('side', 'top') not in ('top', 'bottom', 'both'):
            raise ValueError(ref + ': invalid hardware side')
        for key in ('head_diameter_mm', 'head_height_mm', 'washer_diameter_mm', 'shaft_diameter_mm', 'tool_radius_mm'):
            value = mount.get(key, 0)
            if isinstance(value,bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(ref + ': invalid ' + key)
    for zone in out['height_zones']:
        value=zone.get('max_height_mm')
        if zone.get('side') not in ('top', 'bottom') or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Height zones need a side and non-negative max_height_mm')
        _bounds(zone['bounds'], 4)
    for zone in out['keepouts']:
        _bounds(zone['bounds'], 6)
    for reason in out['waivers'].values():
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('Every waiver must have a reason')
    for item in out['enclosures']:
        if not isinstance(item.get('path'), str) or not item['path']:
            raise ValueError('Enclosures require a STEP path')
    return out


def _bounds(values, count):
    if not isinstance(values,list) or len(values) != count or any(isinstance(v,bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
        raise ValueError('Invalid zone bounds')
    half = count // 2
    if any(values[i] >= values[i + half] for i in range(half)):
        raise ValueError('Zone minimum must be below maximum')


def load(path=None):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')) if path and Path(path).exists() else {})


def save(path, config):
    Path(path).write_text(json.dumps(validate(config), indent=2), encoding='utf-8')


def mount_defaults():
    return dict(expected_plating='NPTH', side='top', head_diameter_mm=5.5,
                head_height_mm=3.0, washer_diameter_mm=7.0, shaft_diameter_mm=3.0,
                tool_radius_mm=3.0)
