"""Finite-array excitation and power-wave diagnostics; no ideal-pattern substitution."""
from __future__ import annotations

import math


def fem_aesa_config(count_x=2, count_y=2, theta_deg=0, phi_deg=0, taper='uniform'):
    """A passive 3 GHz inset-patch starting model, not the Verho author geometry."""
    from .model import validate_config
    if (type(count_x) is not int or type(count_y) is not int
            or not 1 <= count_x <= 4 or not 1 <= count_y <= 4):
        raise ValueError('FEM AESA dimensions must be integers from 1 to 4')
    return validate_config(dict(
        mode='patch', f_start_hz=2.9e9, f_stop_hz=3.1e9, points=3,
        substrate_x_mm=40*count_x, substrate_y_mm=40*count_y,
        thickness_mm=1.524, er=3.38, patch_width_mm=32, patch_length_mm=25.5,
        feed_width_mm=3.2, inset_width_mm=1, inset_length_mm=8,
        air_margin_mm=25, mesh_edge_mm=3, resolution=.45,
        field_z_mm=2, field_grid=41, max_tets=300000,
        advanced=dict(study='array', array_count_x=count_x, array_count_y=count_y,
                      array_pitch_x_mm=40, array_pitch_y_mm=40,
                      array_excitation_mode='scan_angle', array_taper=taper,
                      scan_theta_deg=theta_deg, scan_phi_deg=phi_deg)))


def excitation(config):
    """Return fixed phase-shifter weights in sqrt(W), normalized over all ports.

    EMerge's embedded element fields already include position phase. The steering
    phase is applied once to incident waves, never again to those solved fields.
    """
    import numpy as np
    a = config['advanced']
    nx, ny = a['array_count_x'], a['array_count_y']
    reference = (config['f_start_hz'] + config['f_stop_hz'])/2
    px, py = a['array_phase_x_deg'], a['array_phase_y_deg']
    if a['array_excitation_mode'] == 'scan_angle':
        theta, phi = math.radians(a['scan_theta_deg']), math.radians(a['scan_phi_deg'])
        k0 = 2*math.pi*reference/299792458
        px = math.degrees(-k0*a['array_pitch_x_mm']*.001*math.sin(theta)*math.cos(phi))
        py = math.degrees(-k0*a['array_pitch_y_mm']*.001*math.sin(theta)*math.sin(phi))
    tx = [math.comb(nx-1, i) if a['array_taper']=='binomial' else 1 for i in range(nx)]
    ty = [math.comb(ny-1, i) if a['array_taper']=='binomial' else 1 for i in range(ny)]
    raw = np.asarray([tx[ix]*ty[iy]*np.exp(1j*math.radians(ix*px+iy*py))
                      for iy in range(ny) for ix in range(nx)], dtype=complex)
    weights = raw*math.sqrt(a['array_power_w']/float(np.vdot(raw, raw).real))
    metadata = dict(mode=a['array_excitation_mode'], amplitude_taper=a['array_taper'],
                    phase_reference_frequency_hz=reference,
                    progressive_phase_x_deg=px, progressive_phase_y_deg=py,
                    scan_theta_deg=a['scan_theta_deg'] if a['array_excitation_mode']=='scan_angle' else None,
                    scan_phi_deg=a['scan_phi_deg'] if a['array_excitation_mode']=='scan_angle' else None,
                    weight_unit='sqrt(W)', port_order='X changes fastest, then Y; one port per inset patch',
                    steering_model='fixed phase across frequency; beam squint is not compensated')
    return weights, metadata


def power_accounting(network, weights):
    """Compute b=S a at real-reference power-wave ports; do not clamp violations."""
    import numpy as np
    a = np.asarray(weights, dtype=complex)
    if a.shape != (network.port_count,) or not np.isfinite(a).all():
        raise ValueError('Array weights must be finite and match the ordered network ports')
    incident = float(np.vdot(a, a).real)
    if incident <= 0:
        raise ValueError('At least one array port must be excited')
    rows = []
    for frequency, matrix in zip(network.frequencies_hz, network.s):
        b = matrix @ a
        outgoing = float(np.vdot(b, b).real)
        active = [None if value == 0 else [float((wave/value).real), float((wave/value).imag)]
                  for value, wave in zip(a, b)]
        rows.append(dict(frequency_hz=float(frequency), incident_power_w=incident,
                         outgoing_power_w=outgoing, accepted_power_w=incident-outgoing,
                         active_reflection_ri=active,
                         per_port_net_power_w=(np.abs(a)**2-np.abs(b)**2).tolist(),
                         negative_total_accepted_power=outgoing > incident*(1+1e-9)))
    return rows
