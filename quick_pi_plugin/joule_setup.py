"""Shared inputs for the one-click steady Joule screening workflow."""

from wayricad_runtime.thermal_defaults import screening_defaults


SCREENING_NOTICE = (
    'The quick setup starts with generic FR-4, copper and effective air cooling. '
    'Review the actual material and cooling inputs before using the temperature estimate.'
)
COPPER = {'resistivity_ohm_m': 1.724e-8, 'temperature_coefficient': .00393}
LIMIT_C = 105.
OPTION_FIELDS = {
    'dielectric_k_w_mk': 'Laminate conductivity',
    'board_h_w_m2k': 'Convection coefficient',
    'board_emissivity': 'Surface emissivity',
    'temperature_cap_c': 'Heating stop temperature',
}


def coupling_defaults():
    return {'material_temperature_range_c': [-40., 150.], 'temperature_cap_c': LIMIT_C,
            'max_iterations': 60, 'relaxation': .5, 'temperature_tolerance_c': .01,
            'loss_relative_tolerance': 1e-5}


def preset_values():
    return screening_defaults() | {'temperature_cap_c': LIMIT_C}


def screening_feedback(electrical, ambient, overrides=None):
    """Build explicit, validated settings from ordinary Quick PI controls."""
    from .electrothermal_service import validate_feedback_inputs

    defaults = screening_defaults(ambient)
    keys = ('ambient_c', 'dielectric_k_w_mk', 'copper_k_w_mk', 'board_h_w_m2k', 'board_emissivity')
    settings = {key: defaults[key] for key in keys}
    settings.update(via_plating_mm=electrical['plating_mm'], grid_cells_long_axis=48)
    coupling = coupling_defaults()
    for key, value in (overrides or {}).items():
        if key not in OPTION_FIELDS:
            raise ValueError('Unknown Joule screening setting: ' + key)
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(OPTION_FIELDS[key] + ' must be a finite number.') from exc
        (coupling if key == 'temperature_cap_c' else settings)[key] = number
    feedback = dict(thermal_settings=settings, coupling=coupling, assumptions=[SCREENING_NOTICE])
    validate_feedback_inputs({**feedback, 'electrical': {'options': COPPER}})
    low, high = coupling['material_temperature_range_c']
    if not low <= settings['ambient_c'] < min(high, coupling['temperature_cap_c']):
        raise ValueError('For Joule heating, ambient must be within the material range and below the heating stop.')
    return feedback
