"""Prefill known powers and suitable ambient resistance; capacity stays explicit."""


def initial_study(bundle,ambient_c=20.):
    steady=bundle.get('quick_therm',{})
    ambient=steady.get('ambient_c',ambient_c)
    rows=[]
    for component in steady.get('components',[]):
        # RθJB and package-to-heatsink resistance are not Rθ-to-ambient.
        resistance=component.get('resistance_k_per_w') if steady.get('environment')=='air' and steady.get('board_c') is None and 'heatsink' not in component else None
        rows.append({'reference':component['reference'],'initial_power_W':0.,
                     'step_power_W':component.get('power_w',0.),'step_time_s':1.,
                     'resistance_K_W':resistance,'capacitance_J_K':None})
    if not rows:rows=[{'reference':'U1','initial_power_W':0.,'step_power_W':None,'step_time_s':1.,
                      'resistance_K_W':None,'capacitance_J_K':None}]
    return {'ambient_c':ambient,'initial_temperature_c':ambient,'duration_s':60.,'step_s':.1,'components':rows}
