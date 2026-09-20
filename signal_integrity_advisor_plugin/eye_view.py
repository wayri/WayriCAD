"""Dependency-free plot geometry and offline SVG for the illustrative SI model."""
import html


def plots(result):
    values = [result['min_v'], result['max_v'], 0., result['inputs']['swing_v'],
              min(result['step_response']['voltage_v']),max(result['step_response']['voltage_v'])]
    low, high = min(values), max(values)
    margin = max((high-low)*.12, .01)
    limits = (low-margin, high+margin)
    return [
        ('Illustrative PRBS7 eye — ideal clock, no jitter', 'Time (UI)',
         result['time_ui'], result['traces_v'], limits),
        ('Receiver step response — uniform lossless line', 'Time (ns)',
         result['step_response']['time_ns'], [result['step_response']['voltage_v']], limits),
    ]


def plot_svg(title, xlabel, xs, traces, limits):
    lo, hi = limits
    xmin, xmax = min(xs), max(xs)
    width, height = 720, 270
    x = lambda value: 64+(value-xmin)/(xmax-xmin)*630
    y = lambda value: 222-(value-lo)/(hi-lo)*184
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
             '<rect width="720" height="270" fill="#fafcfe"/>',
             f'<text x="64" y="22" font-size="15">{html.escape(title)}</text>']
    for i in range(5):
        xv = xmin+(xmax-xmin)*i/4
        yv = lo+(hi-lo)*i/4
        parts += [f'<path d="M{x(xv):.2f} 38 V222 M64 {y(yv):.2f} H694" stroke="#dde5eb" fill="none"/>',
                  f'<text x="{x(xv):.2f}" y="240" text-anchor="middle" font-size="11">{xv:.3g}</text>',
                  f'<text x="57" y="{y(yv)+4:.2f}" text-anchor="end" font-size="11">{yv:.3g}</text>']
    for trace in traces:
        points=' '.join(f'{x(a):.2f},{y(b):.2f}' for a,b in zip(xs,trace))
        parts.append(f'<polyline points="{points}" stroke="#147f94" stroke-opacity="{.13 if len(traces)>1 else 1}" stroke-width="1.4" fill="none"/>')
    parts += [f'<text x="380" y="262" text-anchor="middle" font-size="12">{html.escape(xlabel)}</text>',
              '<text x="12" y="30" font-size="12">V</text></svg>']
    return ''.join(parts)


def eye_section(result):
    if result.get('status') == 'UNAVAILABLE':
        return '<h2>Illustrative eye unavailable</h2><p>'+html.escape(result['reason'])+'</p>'
    pictures=''.join(plot_svg(*plot) for plot in plots(result))
    return ('<h2>Illustrative eye and step response</h2><p>Uniform lossless line; '
            'not an IBIS simulation or protocol compliance test.</p>'+pictures+
            f"<p>Sampled center opening: {result['center_opening_v']:.5g} V; "
            f"sampled range: {result['min_v']:.5g} to {result['max_v']:.5g} V.</p>"+
            '<h3>Model assumptions and limits</h3><ul>'+''.join('<li>'+html.escape(note)+'</li>' for note in result['assumptions']+result['limitations'])+'</ul>')


def standalone_html(result):
    import json
    return ('<!doctype html><meta charset="utf-8"><title>WayriCAD illustrative SI eye</title>'
            '<style>body{font:15px system-ui;max-width:960px;margin:30px auto;color:#20303c}svg{width:100%}pre{white-space:pre-wrap}</style>'
            '<h1>WayriCAD Quick SI</h1>'+eye_section(result)+'<h2>Model inputs</h2><pre>'+
            html.escape(json.dumps(result['inputs'],indent=2,allow_nan=False))+'</pre>')
