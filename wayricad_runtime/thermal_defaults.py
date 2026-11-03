"""Explicit workbench starting values, never board-derived material evidence.

The values are the suite's existing illustrative inputs. Missing manufacturer
properties, package thermal paths and material validity ranges stay unknown.
"""
from copy import deepcopy
import math

from .thermal_materials import get_material


FIELD_INFO = {
    'ambient_c': ('Ambient temperature', '°C'),
    'initial_temperature_c': ('Initial temperature', '°C'),
    'fixed_lower_face_c': ('Fixed lower-face temperature', '°C'),
    'enclosure_temperature_c': ('Fixed enclosure temperature', '°C'),
    'board_k_w_mk': ('Effective board conductivity', 'W/(m·K)'),
    'dielectric_k_w_mk': ('Dielectric conductivity', 'W/(m·K)'),
    'copper_k_w_mk': ('Copper conductivity', 'W/(m·K)'),
    'dielectric_volumetric_capacity_j_m3k': ('Dielectric volumetric heat capacity', 'J/(m³·K)'),
    'copper_volumetric_capacity_j_m3k': ('Copper volumetric heat capacity', 'J/(m³·K)'),
    'board_emissivity': ('Board emissivity', '0–1'),
    'board_airflow_m_s': ('Board airflow', 'm/s'),
    'sink_airflow_m_s': ('Sink airflow', 'm/s'),
    'board_h_w_m2k': ('Explicit effective convection', 'W/(m²·K)'),
    'potting_k_w_mk': ('Potting conductivity', 'W/(m·K)'),
    'potting_thickness_mm': ('Potting thickness', 'mm'),
    'potting_outer_h_w_m2k': ('Potting outer convection', 'W/(m²·K)'),
    'via_plating_mm': ('Via plating thickness', 'mm'),
}

NOTICE = ('Illustrative starting assumptions from the existing QuickTherm / Quick PI inputs, '
          'not properties inferred from this PCB. Review the actual laminate, surface finish, '
          'fabrication plating and cooling boundary. Unknown density, specific heat, package '
          'thermal paths and material validity ranges are not invented.')

TEMPERATURE_FIELDS = frozenset(('ambient_c', 'initial_temperature_c',
                               'fixed_lower_face_c', 'enclosure_temperature_c'))


def screening_defaults(ambient_c=20.):
    """Return detached SI values supported by the existing model controls."""
    if isinstance(ambient_c, bool):
        raise ValueError('Ambient temperature must be a finite number above absolute zero.')
    try:
        ambient_c = float(ambient_c)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Ambient temperature must be a finite number above absolute zero.') from exc
    if not math.isfinite(ambient_c) or not -273.15 < ambient_c <= 10000:
        raise ValueError('Ambient temperature must be above absolute zero and at most 10000 °C.')
    dielectric = get_material('fr4-screening')['properties']
    copper = get_material('copper-screening')['properties']
    return {
        'ambient_c': ambient_c, 'initial_temperature_c': ambient_c,
        'fixed_lower_face_c': ambient_c, 'enclosure_temperature_c': ambient_c,
        'board_k_w_mk': dielectric['thermal_conductivity_w_mk']['value'],
        'dielectric_k_w_mk': dielectric['thermal_conductivity_w_mk']['value'],
        'copper_k_w_mk': copper['thermal_conductivity_w_mk']['value'],
        'dielectric_volumetric_capacity_j_m3k': dielectric['volumetric_heat_capacity_j_m3k']['value'],
        'copper_volumetric_capacity_j_m3k': copper['volumetric_heat_capacity_j_m3k']['value'],
        'board_emissivity': .9, 'board_airflow_m_s': 0., 'sink_airflow_m_s': 0.,
        'board_h_w_m2k': 20., 'potting_k_w_mk': 1., 'potting_thickness_mm': 2.,
        'potting_outer_h_w_m2k': 10., 'via_plating_mm': .025,
    }


def populate_settings(current, *, ambient_c=None, replace_existing=False, replace_temperatures=False):
    """Fill only exposed known fields; preserve edited and loaded values by default.

    Invalid nonempty text is retained so the normal input validation can explain
    it. The operation never changes the caller's mapping or its unknown fields.
    Explicit temperature replacement updates only exposed temperatures to the
    selected ambient, leaving existing material and boundary coefficients alone.
    """
    if (not isinstance(current, dict) or type(replace_existing) is not bool
            or type(replace_temperatures) is not bool):
        raise ValueError('Provide current settings and an explicit replacement choice.')
    if ambient_c is None:
        ambient_c = current.get('ambient_c')
        if ambient_c is None or (isinstance(ambient_c, str) and not ambient_c.strip()):
            ambient_c = 20.
    defaults = screening_defaults(ambient_c)
    result = deepcopy(current); changed = []
    for key in current:
        if key not in defaults:
            continue
        missing = current[key] is None or (isinstance(current[key], str) and not current[key].strip())
        replace = replace_existing or (replace_temperatures and key in TEMPERATURE_FIELDS)
        if (missing or replace) and current[key] != defaults[key]:
            result[key] = defaults[key]; changed.append(key)
    return result, changed
