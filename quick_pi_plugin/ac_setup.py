"""Explicit quick-start copper loops; no saved-board geometry is inferred."""
from copy import deepcopy
import math

PRESETS = ('Stacked trace and return', 'Side-by-side outgoing and return',
           'Symmetric split return')


def quick_loop(study, preset, width_mm, thickness_mm, gap_mm, frequency_khz, ripple_rms_a):
    """Prepare a balanced, long-straight cross-section and one RMS harmonic.

    Gap is copper-surface separation; split return divides current equally as
    an explicit model assumption, not a result inferred from the real board.
    """
    if preset not in PRESETS:
        raise ValueError('Choose a supported quick-loop layout.')
    values = [float(value) for value in (width_mm, thickness_mm, gap_mm, frequency_khz, ripple_rms_a)]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError('Quick-loop dimensions, frequency and RMS ripple must be finite and positive.')
    width, thickness, gap, frequency, ripple = values
    def conductor(name, x, y, scale):
        return dict(name=name, x_mm=x, y_mm=y, width_mm=width,
                    thickness_mm=thickness, current_scale=scale)
    conductors = [conductor('Outgoing copper', 0., 0., 1.)]
    if preset == PRESETS[0]:
        conductors.append(conductor('Explicit return', 0., -thickness-gap, -1.))
    elif preset == PRESETS[1]:
        conductors.append(conductor('Explicit return', width+gap, 0., -1.))
    else:
        conductors.extend((conductor('Left return', -width-gap, 0., -.5),
                           conductor('Right return', width+gap, 0., -.5)))
    output = deepcopy(study)
    output.update(conductors=conductors, harmonics=[dict(frequency_hz=frequency*1000., current_rms_a=ripple)])
    output.pop('waveform', None)
    output['mesh_step_mm'] = min(float(output.get('mesh_step_mm', .035)), thickness/2)
    from .ac_analysis import validate_study
    validate_study(output)
    return output
