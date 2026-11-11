"""Explicit illustrative starting assumptions, not inferred board/package data."""

STARTING_VALUES={
    'board_k_w_mk':.3,'dielectric_k_w_mk':.3,'copper_k_w_mk':385.,
    'via_plating_mm':.025,'board_emissivity':.9,
    'board_airflow_m_s':0.,'sink_airflow_m_s':0.,
}


def requires_multilayer(environment, transient=False, storage=False, contacts=False, copper_losses=False):
    return environment in ('forced_air','potting','sealed') or any((transient,storage,contacts,copper_losses))


def missing_power_message(references):
    return ('Enter dissipated power for '+', '.join(references[:12])+
            (' and additional included parts' if len(references)>12 else '')+
            '. Uncheck unknown sources, or use Include known power. Unknown power is not zero.')
