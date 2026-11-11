"""Run protocol discovery and physical screening through the existing RLC engine."""
import math
from .protocol_validation import screen_protocols


def scan_engine(engine, *, rules=None, targets=None, min_confidence=.75,
                tolerance_pct=10.,frequency_mhz=100.,max_sections=5000,max_nets=500,
                cancelled=None,progress=None):
    from .protocol_discovery import discover_protocols
    from .bulk import available_nets,extract_board
    if isinstance(max_nets,bool) or not isinstance(max_nets,int) or not 1<=max_nets<=10000:
        raise ValueError('Protocol net budget must be 1..10000.')
    if isinstance(frequency_mhz,bool) or not isinstance(frequency_mhz,(int,float)) or not math.isfinite(frequency_mhz) or frequency_mhz<=0:
        raise ValueError('Analysis frequency must be positive finite MHz.')
    if isinstance(max_sections,bool) or not isinstance(max_sections,int) or max_sections<1:
        raise ValueError('Section budget must be a positive integer.')
    # Unassigned copper has an empty net name, not a protocol identity.
    discovery=discover_protocols((name for name in available_nets(engine) if name),rules=rules,min_confidence=min_confidence)
    screen_protocols(discovery,{},targets=targets,tolerance_pct=tolerance_pct)
    candidates=sorted({row['net'] for row in discovery['matches'] if not row.get('review_required')})
    selected=candidates[:max_nets]
    extraction=(extract_board(engine,nets=selected,frequency_mhz=frequency_mhz,
                             max_sections=max_sections,cancelled=cancelled,progress=progress)
                if selected else {'nets':[],'coverage':{'complete':True,'selected_nets':0,'extracted_sections':0}})
    if len(candidates)>max_nets:
        extraction['coverage']['complete']=False
        extraction['coverage']['omitted_protocol_nets']=candidates[max_nets:]
        extraction['status']='protocol_net_budget_exceeded'
    result=screen_protocols(discovery,extraction,targets=targets,tolerance_pct=tolerance_pct)
    result['extraction']=extraction
    result['request']=dict(frequency_mhz=frequency_mhz,max_sections=max_sections,max_nets=max_nets,
                           min_confidence=min_confidence,tolerance_pct=tolerance_pct,rules=rules or [])
    return result
