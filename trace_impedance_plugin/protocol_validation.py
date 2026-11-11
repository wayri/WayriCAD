"""Evidence-bounded protocol route screening; never a protocol-compliance pass."""
import math


def screen_protocols(discovery, extraction, *, targets=None, tolerance_pct=10.):
    if isinstance(tolerance_pct,bool) or not isinstance(tolerance_pct,(int,float)) or not math.isfinite(tolerance_pct) or not 0<tolerance_pct<100:
        raise ValueError('Impedance screening tolerance must be between 0 and 100 percent.')
    if targets is not None and not isinstance(targets,dict):
        raise ValueError('Impedance targets must be a JSON object of net/profile names to ohms.')
    targets=dict(targets or {})
    if any(not isinstance(key,str) for key in targets):
        raise ValueError('Impedance target names must be strings.')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in targets.values()):
        raise ValueError('Explicit impedance targets must be positive finite ohms.')
    profiles=discovery.get('profiles',[])
    profiles=profiles if isinstance(profiles,dict) else {p['id']:p for p in profiles}
    allowed=set(profiles)|{row['net'] for row in discovery.get('matches',[])}
    if set(targets)-allowed:raise ValueError('Unknown target net/profile: '+', '.join(sorted(set(targets)-allowed)))
    rows={row['net']:row for row in extraction.get('nets',[])}
    findings=[]
    for match in discovery.get('matches',[]):
        net=match['net'];profile=profiles[match['profile_id']];physical=rows.get(net)
        issues=[];checks=[]
        def issue(code,message,suggestion,section=None,severity='warning'):
            issues.append(dict(code=code,severity=severity,message=message,suggestion=suggestion,
                               section_id=(section or {}).get('section_id'),layer=(section or {}).get('layer')))
        if match.get('review_required'):
            issue('MATCH_REVIEW','Protocol identity is ambiguous or fuzzy.','Review the full net name and endpoint devices; add an exact wildcard/regex rule.',severity='review')
        differential=bool(match.get('differential',profile.get('differential')))
        if differential and not match.get('mate'):
            issue('PAIR_MISSING','A unique differential mate was not identified.','Confirm polarity/lane naming and both routed nets; do not pair across connector instances.')
        if not physical:
            issue('NOT_EXTRACTED','No physical extraction is available for this candidate.','Confirm the candidate, then rerun the saved-board scan; inspect budgets and source changes.')
        else:
            sections=physical.get('sections',[])
            tracks=[s for s in sections if s.get('kind') in ('track','arc')]
            if not tracks:issue('NO_ROUTED_TRACE','No supported routed trace sections were extracted.','Route the net or inspect its zone corridor and terminals; a matching label does not prove a route.')
            if len(physical.get('pads',[]))>2:
                issue('MULTI_TERMINAL','This net has multiple terminals; a branch or stub may exist.','Inspect the route topology and choose source/load pads. Apply device-specific stub and termination requirements.')
            for section in sections:
                for blocker in section.get('blockers',[]):
                    code=blocker.get('code','MODEL_BLOCKER')
                    suggestion=('Save the physical stackup and dielectric properties; verify a continuous adjacent reference plane and return connection.'
                                if any(word in code.upper() for word in ('REFERENCE','STACKUP','DIELECTRIC')) else
                                'Inspect this section in the RLC preview. Supply the missing geometry/model inputs; rerun before relying on totals.')
                    issue(code,blocker.get('message',code),suggestion,section)
                if section.get('kind')=='via':
                    issue('VIA_DISCONTINUITY','A via changes the local transmission-line geometry.','Review return vias, reference transitions and unused barrel stubs; antipad-dependent capacitance needs actual geometry.',section,severity='info')
            if physical.get('zones'):
                issue('ZONE_CORRIDOR_UNKNOWN','Zone/plane regions require terminal-defined current corridors.','Select reviewed start/end pads in Zone/plane mode; do not treat the whole island as a series trace.')
            target=targets.get(net,targets.get(match['profile_id'],profile.get('target_ohm')))
            if differential:
                issue('COUPLED_Z_UNRESOLVED','Automatic board extraction does not solve coupled differential impedance.','Use the actual pair gap, stackup and coupled cross-section/field solver. Never substitute twice single-ended Z0.')
                checks.append(dict(check='differential_impedance',status='unknown',target_ohm=target,measured_ohm=None))
            elif target is None:
                issue('TARGET_REQUIRED','This interface has no universal PCB impedance target.','Enter the target from the endpoint/device design guide. Set I2C pull-up, capacitance and rise-time inputs in Quick SI where applicable.',severity='review')
            elif not match.get('review_required'):
                for section in tracks:
                    value=section.get('impedance_ohm')
                    if value is None or not math.isfinite(value) or section.get('status')!='ok':
                        checks.append(dict(check='section_impedance',section_id=section.get('section_id'),status='unknown',target_ohm=target,measured_ohm=value))
                        issue('Z0_UNKNOWN','This section has no fully supported impedance estimate.','Resolve its stackup/reference/geometry blockers before checking against the target.',section)
                    else:
                        outside=abs(value-target)>target*tolerance_pct/100
                        checks.append(dict(check='section_impedance',section_id=section.get('section_id'),status='outside_target' if outside else 'within_target',target_ohm=target,measured_ohm=value))
                        if outside:
                            correction=('Increase width or reduce reference separation' if value>target else 'Reduce width or increase reference separation')
                            issue('Z0_OUTSIDE_TARGET',f'Section estimate {value:g} ohm differs from {target:g} ohm by more than {tolerance_pct:g}%.',correction+' in a reviewed cross-section sweep; recheck fabrication limits, spacing, coupling and dielectric properties before editing.',section,severity='error')
            if any(s.get('status')!='ok' for s in sections) or physical.get('status')!='ok':
                issue('INCOMPLETE_GEOMETRY','Some physical terms remain unresolved.','Review missing sections, reference coverage and via/zone terms; partial extraction cannot establish a passing route.')
        status=('needs_review' if match.get('review_required') else 'outside_target' if any(i['severity']=='error' for i in issues) else
                'unresolved' if any(i['severity'] in ('warning','review') for i in issues) else 'within_screening_target')
        findings.append(dict(net=net,profile_id=match['profile_id'],confidence=match['confidence'],mate=match.get('mate'),
                             status=status,checks=checks,issues=issues,match=match))
    complete=bool(extraction.get('coverage',{}).get('complete'))
    return dict(schema='wayricad.rlc-protocol-screen/v1',status='screened' if complete else 'incomplete',
                tolerance_pct=tolerance_pct,targets=targets,findings=findings,discovery=discovery,
                coverage=extraction.get('coverage',{}),protocol_compliance='not_evaluated',
                limitations=['Name inference is not connectivity or device identification.',
                             'Nominal targets are editable screening assumptions, not universal protocol limits.',
                             'Differential coupling, receiver timing/eye masks, terminations and I2C pull-ups need additional models/inputs.',
                             'Suggestions are read-only; no PCB tracks, rules, widths or stackup are changed.'])
