"""Explicit common return-domain assignment for independent SI study cases."""
from copy import deepcopy


def apply_return_nets(cases, return_nets):
    """Copy selected returns, clearing endpoint assumptions specific to each case."""
    nets = list(dict.fromkeys(return_nets))
    if any(not isinstance(net, str) or not net.strip() for net in nets):
        raise ValueError('Return net names must be nonempty strings.')
    for case in cases:
        if case.get('net') in nets:
            raise ValueError('Study case '+str(case.get('id', case['net']))+
                             ' is a selected return net. Choose its return separately.')
    result = deepcopy(cases)
    for case in result:
        inputs = case.setdefault('inputs', {})
        for key in ('return_nets', 'return_terminal_ids', 'return_terminal_roles'):
            inputs.pop(key, None)
        if nets: inputs['return_nets'] = list(nets)
    return result
