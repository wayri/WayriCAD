"""Stable S-parameter names, including unambiguous multi-digit port indices."""


def s_key(response, excitation):
    """Keep historical S11 names; delimit any multi-digit port (S1_11)."""
    return (f'S{response}{excitation}' if response < 10 and excitation < 10
            else f'S{response}_{excitation}')
