"""Explicit independent supply/return copper loops at prescribed DC current."""
import copy
import math

_ALLOWED={'net','source_terminal','sink_terminal','edge_mm','plating_mm','mesh_backend','mesh_sizing','options','stackup_override'}


def return_request(electrical,definition):
    """Declare return current from the load-ground pad to source-ground pad.

    Copper voltage is gauge invariant. The raw return solve uses the explicit
    supply voltage as an auxiliary reference, retaining its native evidence.
    The summary supplies the offset that makes source ground zero volts.
    """
    from .service import sink_requests
    if not isinstance(definition,dict) or set(definition)-_ALLOWED:
        raise ValueError('Return conduction requires only an explicit net, source/sink pads and copper mesh/material settings.')
    for key in ('net','source_terminal','sink_terminal'):
        if not isinstance(definition.get(key),str) or not definition[key].strip():
            raise ValueError('Return conduction requires explicit '+key+'.')
    if definition['net']==electrical['net'] or definition['source_terminal']==definition['sink_terminal']:
        raise ValueError('Choose a separate return net and two different load-ground/source-ground pads.')
    if (electrical.get('model_dimension','2.5d')!='2.5d' or electrical.get('series') or
            electrical.get('package_conduction') or electrical.get('load_resistance_ohm') is not None):
        raise ValueError('Explicit DC loops support 2.5D linear copper with one prescribed-current load; packages, series, 3D and resistive loads are unsupported.')
    sinks=sink_requests(electrical)
    if len(sinks)!=1:
        raise ValueError('Case-level return_conduction requires one supply load; use shared_returns to solve common return copper for multiple loads.')
    request={key:copy.deepcopy(value) for key,value in electrical.items()
             if key in ('edge_mm','plating_mm','mesh_backend','mesh_sizing','options','stackup_override','source_voltage')}
    request.update(copy.deepcopy(definition),action='solve',model_dimension='2.5d',
                   sink_current=sinks[0]['current_A'])
    return request


def summarize_loop(electrical,supply,returned,definition):
    """Combine linear drop/loss and recheck the load's physical rail voltage."""
    from .service import sink_requests
    sink=sink_requests(electrical)[0];current=sink['current_A']
    def number(value,label):
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
            raise ValueError('Loop result needs finite '+label+'.')
        return float(value)
    for result in (supply,returned):
        if not math.isclose(number(result.get('sink_current_A'),'sink current'),current,rel_tol=1e-9,abs_tol=1e-12):
            raise ValueError('Supply and return currents differ; loop result invalidated.')
        if number(result.get('energy_relative_error'),'energy balance')>1e-6:
            raise ValueError('Loop copper solve did not satisfy its energy balance.')
        if number(result.get('current_balance_error_A'),'current balance')>max(1e-8,current*1e-6):
            raise ValueError('Loop copper solve did not satisfy current conservation.')
    ds=number(supply.get('voltage_drop_V'),'supply drop');dr=number(returned.get('voltage_drop_V'),'return drop')
    ps=number(supply.get('total_power_W'),'supply loss');pr=number(returned.get('total_power_W'),'return loss')
    if min(ds,dr,ps,pr)<0:raise ValueError('Passive loop drops and Joule losses cannot be negative.')
    voltage=number(electrical['source_voltage'],'source voltage');delivered=voltage-ds-dr
    low=sink.get('min_voltage_V',0.);high=sink.get('max_voltage_V')
    if high is None:high=math.inf
    budget=electrical.get('source_current_limit')
    budget_ok=budget is None or current<=number(budget,'source current budget')+max(1e-12,current*1e-12)
    feasible=budget_ok and low-1e-12<=delivered<=high+1e-12
    offset=-number(returned.get('sink_voltage_V'),'auxiliary return reference')
    return {'status':'COMPLETED' if feasible else 'INFEASIBLE','feasible':feasible,
            'source_voltage_V':voltage,'current_A':current,'supply_drop_V':ds,'return_drop_V':dr,
            'total_drop_V':ds+dr,'delivered_load_voltage_V':delivered,
            'supply_loss_W':ps,'return_loss_W':pr,'total_loss_W':ps+pr,
            'supply_resistance_ohm':ds/current,'return_resistance_ohm':dr/current,
            'loop_resistance_ohm':(ds+dr)/current,'source_current_budget_met':budget_ok,
            'load_voltage_limits':{key:sink[key] for key in ('min_voltage_V','max_voltage_V') if key in sink},
            'return_voltage_reference':{'zero_terminal':definition['sink_terminal'],
                'add_to_raw_potential_V':offset,'load_ground_voltage_V':dr,
                'current_direction':'load-ground source_terminal to source-ground sink_terminal'},
            'notice':'Independent fixed-temperature linear copper paths at the same current. '
                     'Delivered voltage is measured across the load power and ground pads. '
                     'Return report potentials use an auxiliary reference; add the declared offset for source-ground zero. '
                     'No shared-return coupling, inter-net fields, connector contact loss or temperature feedback is inferred.'}
