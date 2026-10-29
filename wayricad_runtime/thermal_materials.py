"""Small offline thermal reference library with explicit review and SI units.

Typical data and inherited screening assumptions remain distinguishable. These
records supply no electrical rating, validity range or automatic board identity.
"""
from __future__ import annotations

from copy import deepcopy
import math

PROPERTY_UNITS = {
    'thermal_conductivity_w_mk': 'W/(m·K)',
    'volumetric_heat_capacity_j_m3k': 'J/(m³·K)',
    'density_kg_m3': 'kg/m³',
    'specific_heat_j_kgk': 'J/(kg·K)',
}
PROPERTY_LABELS = {
    'thermal_conductivity_w_mk': 'Thermal conductivity',
    'volumetric_heat_capacity_j_m3k': 'Volumetric heat capacity',
    'density_kg_m3': 'Density',
    'specific_heat_j_kgk': 'Specific heat capacity',
}


def _property(value, name, conditions, method='', basis='typical'):
    return {'value': value, 'unit': PROPERTY_UNITS[name], 'conditions': conditions,
            'method': method, 'basis': basis}


def _record(identifier, name, category, source, properties, note):
    return {'id': identifier, 'name': name, 'category': category, 'source': source,
            'properties': properties, 'note': note}


_ROGERS = {
    'title': 'Rogers RO4000 Series data sheet, page 3',
    'url': 'https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf',
    'revision': '1592 080322; PUB# 92-004 (2022)', 'verified_on': '2026-10-29',
}
_ISOLA = {
    'title': 'Isola 370HR data sheet, typical values table, page 2',
    'url': 'https://www.isola-group.com/wp-content/uploads/data-sheets/370hr.pdf',
    'revision': 'Updated April 15, 2021; footer Revision C', 'verified_on': '2026-10-29',
}
_HENKEL = {
    'title': 'Henkel BERGQUIST GAP PAD TGP 1500 technical data sheet, page 1',
    'url': 'https://datasheets.tdx.henkel.com/BERGQUIST-GAP-PAD-TGP-1500-en_GL.pdf',
    'revision': 'October 2020', 'verified_on': '2026-10-29',
}
_REPOSITORY = {
    'title': 'WayriCAD inherited QuickTherm / Quick PI illustrative inputs',
    'url': '', 'revision': 'quick_therm_plugin/ui.py and quick_pi_plugin/electrothermal_ui.py',
    'verified_on': '2026-10-29',
}
_K = 'thermal_conductivity_w_mk'
_CV = 'volumetric_heat_capacity_j_m3k'
_RHO = 'density_kg_m3'
_CP = 'specific_heat_j_kgk'
_UNKNOWN = 'Temperature and direction are not specified in the cited property row.'
_ASSUMPTION = 'Illustrative constant inherited from repository inputs; no material grade, temperature range or qualification established.'

_MATERIALS = (
    _record('copper-screening', 'Copper · illustrative screening inputs', 'metal', _REPOSITORY,
            {_K: _property(385., _K, _ASSUMPTION, basis='illustrative'),
             _CV: _property(3450000., _CV, _ASSUMPTION, basis='illustrative')},
            'Review foil/plating purity and temperature behavior. This is not a manufacturer copper specification.'),
    _record('fr4-screening', 'Generic FR-4 · illustrative screening inputs', 'laminate', _REPOSITORY,
            {_K: _property(.3, _K, _ASSUMPTION, basis='illustrative'),
             _CV: _property(1800000., _CV, _ASSUMPTION, basis='illustrative')},
            'Generic FR-4 does not identify a laminate or its anisotropy. An effective copper-filled board needs a separate model.'),
    _record('isola-370hr', 'Isola 370HR · manufacturer typical', 'laminate', _ISOLA,
            {_K: _property(.4, _K, _UNKNOWN, 'ASTM E1952')},
            'Product-specific typical data. The sheet does not establish a scalar conductivity validity range or heat capacity.'),
    _record('rogers-ro4003c', 'Rogers RO4003C · manufacturer typical', 'laminate', _ROGERS,
            {_K: _property(.71, _K, '80 °C; direction unspecified.', 'ASTM C518'),
             _RHO: _property(1790., _RHO, '23 °C; 1.79 g/cm³ converted to kg/m³.', 'ASTM D792')},
            'Specific to RO4003C. A measurement condition is not a guaranteed operating or constant-property range.'),
    _record('rogers-ro4350b', 'Rogers RO4350B · manufacturer typical', 'laminate', _ROGERS,
            {_K: _property(.69, _K, '80 °C; direction unspecified.', 'ASTM C518'),
             _RHO: _property(1860., _RHO, '23 °C; 1.86 g/cm³ converted to kg/m³.', 'ASTM D792')},
            'Specific to RO4350B. Density has a different measurement temperature from conductivity; heat capacity is unknown.'),
    _record('henkel-tgp1500', 'Henkel GAP PAD TGP 1500 · manufacturer typical', 'interface', _HENKEL,
            {_K: _property(1.5, _K, 'Cured material; property-row temperature unspecified.', 'ASTM D5470'),
             _RHO: _property(2100., _RHO, 'Bulk rubber; temperature unspecified. 2.1 g/cm³ converted to kg/m³.', 'ASTM D792'),
             _CP: _property(1000., _CP, 'Temperature unspecified. 1.0 J/(g·K) converted to J/(kg·K).', 'ASTM E1269'),
             _CV: _property(2100000., _CV, 'Derived 2100 kg/m³ × 1000 J/(kg·K); constant typical inputs with no stated temperature.',
                            'Product of cited density and specific heat', basis='derived_typical')},
            'Actual interface resistance depends on thickness, compression and surfaces; bulk conductivity does not include a selected assembly contact model.'),
    _record('custom', 'Custom · reviewed user inputs', 'custom',
            {'title': 'User-supplied material evidence', 'url': '', 'revision': '', 'verified_on': ''}, {},
            'Enter only known positive SI properties. Record a source and the applicable temperature, direction and conditions in your review note.'),
)


def list_materials(category=None):
    """Detached records; modifying a selection cannot mutate the library."""
    return deepcopy([row for row in _MATERIALS if category is None or row['category'] == category])


def get_material(identifier):
    for record in _MATERIALS:
        if record['id'] == identifier:
            return deepcopy(record)
    raise ValueError('Unknown thermal material preset: ' + str(identifier))


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + ' must be a known finite positive SI value.')
    return float(value)


def review_material(identifier, *, selected=None, overrides=None, reviewed=False, review_note=''):
    """Create explicit reviewed evidence; unknown properties are never filled.

    ``selected`` names exactly the properties to apply. ``overrides`` contains
    numeric SI values only and retains the original source plus override status.
    """
    if reviewed is not True:
        raise ValueError('Review the material, units and applicability before applying it.')
    record = get_material(identifier); overrides = {} if overrides is None else overrides
    if not isinstance(overrides, dict) or set(overrides) - PROPERTY_UNITS.keys():
        raise ValueError('Unsupported thermal material property override.')
    for key, value in overrides.items():
        value = _positive(value, PROPERTY_LABELS[key])
        if key not in record['properties'] or value != record['properties'][key]['value']:
            record['properties'][key] = _property(value, key, 'User override; applicability recorded in review note.', basis='user_override')
    if selected is None:
        selected = list(record['properties'])
    if (not isinstance(selected, (list, tuple)) or not selected or
            any(not isinstance(key, str) for key in selected) or len(selected) != len(set(selected))):
        raise ValueError('Select one or more distinct known properties to apply.')
    if set(selected) - record['properties'].keys():
        raise ValueError('A selected material property is unknown; enter and review an explicit value.')
    if not isinstance(review_note, str) or len(review_note) > 4096:
        raise ValueError('Material review note must be bounded text.')
    if (identifier == 'custom' or any(record['properties'][key]['basis'] == 'user_override' for key in selected)) and not review_note.strip():
        raise ValueError('Custom values require a source/conditions review note.')
    record['properties'] = {key: record['properties'][key] for key in selected}
    return validate_material_selection({'schema': 1, **record, 'reviewed': True, 'review_note': review_note})


def validate_material_selection(selection):
    if not isinstance(selection, dict) or type(selection.get('schema')) is not int or selection['schema'] != 1 or selection.get('reviewed') is not True:
        raise ValueError('An explicitly reviewed schema-1 material selection is required.')
    allowed = {'schema', 'id', 'name', 'category', 'source', 'properties', 'note', 'reviewed', 'review_note'}
    if set(selection) - allowed:
        raise ValueError('Unknown thermal material selection field.')
    for field in ('id', 'name', 'category', 'note', 'review_note'):
        if not isinstance(selection.get(field), str) or len(selection[field]) > 4096:
            raise ValueError('Material metadata must be bounded text.')
    source = selection.get('source')
    if not isinstance(source, dict) or not source.get('title') or set(source) - {'title', 'url', 'revision', 'verified_on'}:
        raise ValueError('Material selection needs bounded source evidence.')
    if any(not isinstance(value, str) or len(value) > 4096 for value in source.values()):
        raise ValueError('Material source fields must be bounded text.')
    original = get_material(selection['id'])
    if any(selection[field] != original[field] for field in ('name', 'category', 'source', 'note')):
        raise ValueError('Keep the original preset identity/source; record custom evidence in the review note.')
    properties = selection.get('properties')
    if not isinstance(properties, dict) or not properties or set(properties) - PROPERTY_UNITS.keys():
        raise ValueError('Select known supported thermal material properties.')
    for key, prop in properties.items():
        if not isinstance(prop, dict) or set(prop) != {'value', 'unit', 'conditions', 'method', 'basis'}:
            raise ValueError('Each material property needs value, unit, conditions, method and basis.')
        _positive(prop['value'], key)
        if prop['unit'] != PROPERTY_UNITS[key]:
            raise ValueError(key + ': units must match the declared SI property.')
        for field in ('conditions', 'method', 'basis'):
            if not isinstance(prop[field], str) or len(prop[field]) > 4096:
                raise ValueError('Material property evidence must be bounded text.')
        if prop['basis'] == 'user_override':
            if not selection['review_note'].strip():
                raise ValueError('Custom values require a source/conditions review note.')
        elif prop != original['properties'].get(key):
            raise ValueError('Changed material values must be marked as user overrides and reviewed.')
    return deepcopy(selection)


def apply_material_selection(settings, selection, bindings):
    """Return a copy with only explicitly mapped selected numeric fields changed.

    Callers retain ``selection`` in study provenance. No ambient, emissivity,
    electrical property or material temperature-validity range is invented.
    """
    selection = validate_material_selection(selection)
    if not isinstance(settings, dict) or not isinstance(bindings, dict):
        raise ValueError('Material application needs settings and explicit property-to-setting bindings.')
    if set(bindings) - PROPERTY_UNITS.keys() or any(not isinstance(key, str) or not key for key in bindings.values()):
        raise ValueError('Unsupported material property binding.')
    if len(set(bindings.values())) != len(bindings):
        raise ValueError('Material properties must not overwrite the same setting.')
    if set(selection['properties']) - bindings.keys():
        raise ValueError('Each selected property needs an explicit target setting.')
    result = deepcopy(settings)
    for key, prop in selection['properties'].items():
        result[bindings[key]] = prop['value']
    return result


def matching_material_selections(records, current_values):
    """Retain provenance only while every explicitly applied value still matches."""
    if not isinstance(records, dict) or len(records) > 16:
        raise ValueError('Material library provenance must be a bounded mapping.')
    result = {}
    for role, entry in records.items():
        if not isinstance(role, str) or not isinstance(entry, dict) or set(entry) != {'selection', 'bindings'}:
            raise ValueError('Material library provenance needs a selection and explicit bindings.')
        selection = validate_material_selection(entry['selection']); bindings = entry['bindings']
        applied = apply_material_selection({}, selection, bindings)
        if all(current_values.get(key) == value for key, value in applied.items()):
            result[role] = deepcopy(entry)
    return result
