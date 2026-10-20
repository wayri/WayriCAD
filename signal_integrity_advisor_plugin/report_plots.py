"""Offline Matplotlib route plots with gaps for unresolved section values."""
from __future__ import annotations

import base64
import io
import math


def plot_section(report):
    """Return three embedded PNG plots; distances are mm, delay ns and R/Z ohms."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    segments=report['path'].get('segments',[])
    distance=[0.0]
    delay=[0.0]
    resistance=[0.0]
    impedance_x=[]
    impedance=[]
    ideal_impedance=[]
    assumed_er=report.get('inputs',{}).get('assumed_epsilon_eff')
    for segment in segments:
        length=segment.get('length_mm',0.0)
        distance.append(distance[-1]+length)
        value=length*math.sqrt(assumed_er)/299.792458 if assumed_er is not None else segment.get('propagation_delay_ns',segment.get('screening_delay_ns'))
        delay.append(delay[-1]+value if value is not None and math.isfinite(delay[-1]) else math.nan)
        value=segment.get('resistance_ohm')
        resistance.append(resistance[-1]+value if value is not None and math.isfinite(resistance[-1]) else math.nan)
        impedance_x.append((distance[-1]+distance[-2])/2)
        impedance.append(segment.get('impedance_ohm') if segment.get('impedance_ohm') is not None else math.nan)
        ideal_impedance.append(segment.get('screening_z0_ohm') if segment.get('screening_z0_ohm') is not None else math.nan)
    plots=[]
    from wayricad_runtime.interactive_plots import interactive_plot
    for title,ylabel in [('Propagation delay along route','Delay (ns)'),('Section impedance along route','Single-ended Z0 (ohm)'),('DC resistance along route','Resistance (ohm)')]:
        figure=Figure(figsize=(9,3.5),dpi=120);FigureCanvasAgg(figure)
        ax=figure.add_subplot(111)
        if title.startswith('Propagation'):
            ax.plot(distance,delay,color='#148e9b',marker='.',label='First-order travel time')
        elif title.startswith('Section'):
            ax.scatter(impedance_x,impedance,color='#175f93',label='Reference-covered section')
            ax.scatter(impedance_x,ideal_impedance,facecolors='none',edgecolors='#bb771c',label='Ideal continuous-plane estimate')
            assumed=report.get('inputs',{}).get('assumed_z0_ohm')
            if assumed is not None:ax.axhline(assumed,color='#984cad',linestyle='--',label='User uniform Z0 assumption')
        else:ax.plot(distance,resistance,color='#a45246',marker='.',label='Copper path DC resistance')
        for index,segment in enumerate(segments):
            if segment.get('kind')=='via':ax.axvline(distance[index],color='#667788',alpha=.25,linewidth=.7)
        ax.set(title=title,xlabel='Distance from source (mm)',ylabel=ylabel)
        ax.grid(alpha=.2);ax.legend(fontsize=8);figure.tight_layout()
        stream=io.BytesIO();figure.savefig(stream,format='png');figure.clear()
        image=base64.b64encode(stream.getvalue()).decode('ascii')
        rows = ([[x,y,y,'Route sample'] for x,y in zip(distance,delay)] if title.startswith('Propagation') else
                [[x,y,y,'Extracted section'] for x,y in zip(impedance_x,impedance)]+[[x,y,y,'Ideal section estimate'] for x,y in zip(impedance_x,ideal_impedance)] if title.startswith('Section') else
                [[x,y,y,'Route sample'] for x,y in zip(distance,resistance)])
        plots.append(interactive_plot(title,rows,ylabel,y_unit=ylabel,connect=not title.startswith('Section')))
        plots.append('<details><summary>Static export</summary><figure><figcaption>'+title+'</figcaption><img style="width:100%;height:auto" alt="'+title+'" src="data:image/png;base64,'+image+'"></figure></details>')
    return '<h2>Route plots</h2><p>Vertical markers indicate vias. Missing impedance values are omitted; unknown delay/resistance interrupts the cumulative curve. Ideal estimates do not resolve discontinuity reflections or differential coupling.</p>'+''.join(plots)


def study_html(report):
    """Compare independent route screens, retaining every error and unknown."""
    from html import escape
    import json
    from wayricad_runtime.report_ui import enhance_report, provenance
    cases=report.get('cases',[])
    document='<!doctype html><html lang="en"><meta charset="utf-8"><title>WayriCAD Quick SI study</title><h1>WayriCAD Quick SI · Independent route study</h1><h2>Case comparison</h2><table><thead><tr><th>Case</th><th>Net</th><th>Source → receiver</th><th>Status</th><th>Delay ns</th><th>Z0 Ω</th><th>Return review</th><th>Next action / error</th></tr></thead><tbody>'
    details=[]
    for index,case in enumerate(cases):
        child=case.get('report') or {};identifier='si-case-'+str(index)
        blockers=child.get('blockers',[])
        next_action=case.get('error') or '; '.join(str(row.get('action',row.get('message',''))) for row in blockers) or 'Review model coverage and assumptions'
        values=[case.get('id',index+1),case.get('net','Unknown'),str(case.get('start','Unknown'))+' → '+str(case.get('end','Unknown')),case.get('status','UNKNOWN'),child.get('delay_ns'),child.get('z0_ohm'),case.get('return_status','Not requested'),next_action]
        document+='<tr><td><a href="#'+identifier+'">'+escape(str(values[0]))+'</a></td>'+''.join('<td>'+escape('Unknown' if value is None else str(value))+'</td>' for value in values[1:])+'</tr>'
        detail='<details id="'+identifier+'"><summary>'+escape(str(values[0]))+' · '+escape(str(values[1]))+' · '+escape(str(case.get('status','UNKNOWN')))+'</summary>'
        if case.get('error'):detail+='<p><strong>Case failed:</strong> '+escape(str(case['error']))+'</p>'
        if child:
            detail+='<p>'+escape(str(child.get('delay_source','Delay source unavailable')))+'</p>'
            detail+='<ul>'+''.join('<li>'+escape(str(note))+'</li>' for note in child.get('notes',[]))+'</ul>'
            detail+=plot_section(child)
            if child.get('return_path'):
                from wayricad_runtime.return_path import html_details
                detail+=html_details(child['return_path'])
        detail+='<details class="report-evidence"><summary>Exact case inputs, results and source object identities</summary><pre>'+escape(json.dumps(case,indent=2,ensure_ascii=False,allow_nan=False))+'</pre></details></details>'
        details.append(detail)
    document+='</tbody></table>'+crosstalk_html(report)+'<h2>Individual case evidence</h2>'+''.join(details)+'</html>'
    summary=report.get('summary',{})
    notice=('Route cases are independent. Optional crosstalk results describe local parallel sections under an explicit ideal homogeneous reference and matched ports. No whole-route coupling waveform, simultaneous switching or whole-bus qualification is claimed. Error and incomplete cases remain in the report.'
            if report.get('crosstalk') else 'Cases are independent source-to-receiver screens. This comparison does not solve inter-net coupling, crosstalk, simultaneous switching or whole-bus qualification. Error and incomplete cases remain in the report.')
    return enhance_report(document,status=report.get('status','UNKNOWN'),summary=[('Cases',summary.get('cases',len(cases))),('Reported',summary.get('reported',sum(bool(case.get('report')) for case in cases))),('Errors',summary.get('errors',sum(case.get('status')=='ERROR' for case in cases))),('Model',report.get('model','Independent route screens'))],notice=notice,provenance=provenance(report))


def crosstalk_html(report):
    """Local directed coupling evidence, exact assumptions and route crosslinks."""
    from html import escape
    import json
    from wayricad_runtime.interactive_plots import interactive_plot
    pairs=report.get('crosstalk',[])
    if not pairs:return ''
    indexes={case['id']:index for index,case in enumerate(report['cases'])}
    document='<h2>Local crosstalk sections</h2><p>Peaks below are individual section estimates. They are not a sum, whole-route waveform or compliance result. FEXT zero is a property of the assumed homogeneous model, not a board measurement.</p>'
    for pair in pairs:
        document+='<section><h3>'+escape(pair['id'])+' · '+escape(pair['status'])+'</h3><p>'
        for role in ('aggressor','victim'):
            identifier=pair[role]
            document+=escape(role.title())+': <a href="#si-case-'+str(indexes[identifier])+'">'+escape(identifier)+'</a> '
        document+='</p><p>Reference model: '+escape(json.dumps(pair['reference'],ensure_ascii=False))+'</p><ul>'
        document+=''.join('<li>'+escape(note)+'</li>' for note in pair['limitations'])+'</ul>'
        document+='<table><tr><th>Layer / direction</th><th>Overlap mm</th><th>Gap mm</th><th>Width / copper mm</th><th>Zeven / Zodd Ω</th><th>Matched port Ω</th><th>Delay ns</th><th>NEXT mV / victim side</th><th>FEXT mV (ideal)</th><th>Modal / coupling refinement</th></tr>'
        for i,s in enumerate(pair['sections']):
            peak=(f"< {s['next_numerical_resolution_v']*1000:.3g} (numerical floor)" if s['coupling_numerical_status']=='BELOW_NUMERICAL_FLOOR' else f"{s['next_peak_v']*1000:.4g}")
            values=[s['layer']+' / '+s['direction'],s['length_mm'],s['gap_mm'],
                    f"{s['width_mm']:.6g} / {s['copper_thickness_mm']:.6g}",
                    f"{s['z_even_ohm']:.6g} / {s['z_odd_ohm']:.6g}",s['matched_port_ohm'],s['delay_ns'],
                    peak+' / '+s['near_victim_role'],s['fext_peak_v']*1000,
                    f"{s['panel_refinement_relative']:.3g} / Δk={s['coupling_refinement_absolute']:.3g} ({s['coupling_numerical_status']})"]
            document+='<tr>'+''.join('<td>'+escape(f'{v:.6g}' if isinstance(v,(int,float)) else str(v))+'</td>' for v in values)+'</tr>'
        document+='</table>'
        for role,c in pair.get('coverage',{}).items():
            document+='<p>'+escape(f"{role.title()}: {c['supported_overlap_mm']:.6g} mm supported overlap of {c['route_length_mm']:.6g} mm; {c['unmodeled_length_mm']:.6g} mm unmodeled. Layers: "+', '.join(c['layers']))+'</p>'
        document+='<ul>'+''.join('<li>Unresolved: '+escape(row['reason'])+'</li>' for row in pair['unresolved'])+'</ul>'
        for i,s in enumerate(pair['sections']):
            if s['coupling_numerical_status']=='BELOW_NUMERICAL_FLOOR':continue
            document+='<details><summary>Section '+str(i+1)+' local near-end step</summary>'
            document+=interactive_plot(pair['id']+' · section '+str(i+1)+' NEXT',
                                       [[t,v,v,'Local NEXT'] for t,v in s['next_samples']],
                                       'V',x_unit='ns',y_unit='V',connect=True)+'</details>'
        document+='<details><summary>Exact coupling inputs, geometry and numerical evidence</summary><pre>'+escape(json.dumps(pair,indent=2,ensure_ascii=False,allow_nan=False))+'</pre></details></section>'
    return document
