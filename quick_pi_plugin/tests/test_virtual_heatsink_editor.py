import pytest

from quick_pi_plugin.virtual_heatsink_editor import parse_heatsink_inputs


def test_resistance_only_path_has_no_fabricated_envelope():
    sink = parse_heatsink_inputs('U1', 'resistance_only', '', '', '', '0.2', '8', '')
    assert sink == {'shape': 'resistance_only', 'contact_k_per_w': 0.2,
                    'theta_sa_air_k_per_w': 8.0}


def test_fin_envelope_does_not_generate_thermal_rating():
    sink = parse_heatsink_inputs('U1', 'straight_fin', '40', '40', '15', '0.2', '', '25')
    assert sink['width_mm'] == 40
    assert sink['theta_sa_vacuum_k_per_w'] == 25
    assert 'theta_sa_air_k_per_w' not in sink


@pytest.mark.parametrize('contact,air', [('', '8'), ('0.1', ''), ('NaN', '8')])
def test_required_thermal_inputs_are_explicit(contact, air):
    with pytest.raises(ValueError):
        parse_heatsink_inputs('U1', 'plate', '40', '40', '3', contact, air, '')
