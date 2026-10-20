"""Account for declared thermal sources without inventing transfer paths."""
from __future__ import annotations

from collections import Counter
from html import escape
import math
from pathlib import Path


def _watts(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def thermal_sankey_data(bundle):
    """Return source watts, omissions and a left-to-right dissipation graph.

    Component powers come from solved scoped inputs, overridden by board-model
    source powers when available. Conductor and package-contact Joule sources
    are distinct inputs; heat-balance totals and contact heat flows are never
    added again. This is generated heat, not environmental outflow or storage.
    """
    thermal = bundle.get('quick_therm') or {}
    network = bundle.get('thermal_network') or {}
    rows = thermal.get('components', [])
    counts = Counter(str(row.get('reference', '')) for row in rows)
    network_rows = network.get('components', [])
    network_counts = Counter(str(row.get('reference', '')) for row in network_rows)
    overrides = {str(row.get('reference', '')): row for row in network_rows}
    nodes = [{'id': 'total', 'label': 'Total known dissipation'}]
    links, omitted, zero = [], [], []

    def add(identifier, label, value):
        power = _watts(value)
        if power is None:
            omitted.append(label + ': unknown or invalid power')
            return
        nodes.append({'id': identifier, 'label': label})
        if power == 0:
            zero.append(label)
        else:
            links.append({'source': identifier, 'target': 'total', 'value': power})

    for index, row in enumerate(rows):
        ref = str(row.get('reference', ''))
        if not ref or counts[ref] != 1 or network_counts[ref] > 1:
            omitted.append((ref or 'Unnamed part') + ': ambiguous component identity')
            continue
        source = overrides.get(ref, {})
        add('part:' + str(index), ref, source.get('power_w', row.get('power_w')))
    for row in thermal.get('coverage', {}).get('excluded', []):
        omitted.append(str(row.get('reference', 'Unnamed part')) + ': ' +
                       ', '.join(str(issue) for issue in row.get('issues', ['excluded'])))
    # Only retained solver source evidence counts. Request/import aggregate
    # totals can include contact heat as well, and would double count it.
    for key, prefix in (('copper_loss_sources', 'Copper I²R'),
                        ('package_joule_sources', 'Contact I²R')):
        sources = network.get(key, [])
        identifiers = Counter(str(row.get('id', '')) for row in sources)
        for index, row in enumerate(sources):
            identity = str(row.get('id', ''))
            label = prefix + ': ' + (identity or str(index + 1))
            if not identity or identifiers[identity] != 1:
                omitted.append(label + ': ambiguous source identity')
                continue
            add(key + ':' + str(index), label, row.get('power_w'))
    return {'nodes': nodes, 'links': links, 'total_w': math.fsum(row['value'] for row in links),
            'omitted': list(dict.fromkeys(omitted)), 'zero_power': zero}


def thermal_sankey_html(bundle):
    """Render an offline generated-heat diagram and its coverage accounting."""
    from wayricad_runtime.sankey import sankey_html
    data = thermal_sankey_data(bundle)
    labels = {row['id']: row['label'] for row in data['nodes']}
    links = sorted(data['links'], key=lambda row: (-row['value'], labels[row['source']], row['source']))
    diagram_links = links[:30]
    diagram_nodes = [data['nodes'][0]] + [
        {'id': row['source'], 'label': labels[row['source']]} for row in diagram_links]
    note = ('Left to right: individual declared heat sources → total known dissipation. '
            'Saved steady/reference operating point, in watts; not heat-transfer paths, '
            'environmental outflow or transient stored heat. Unknown and excluded parts '
            'are omitted from the numeric total, not treated as zero.')
    if len(links) > 30:
        other = links[30:]
        diagram_nodes.append({'id': 'other', 'label': 'Other known sources (' + str(len(other)) + ')'})
        diagram_links.append({'source': 'other', 'target': 'total',
                              'value': math.fsum(row['value'] for row in other)})
        note += ' The diagram groups sources after the largest 30; exact source watts remain in the table below.'
    html = sankey_html('Thermal dissipation', diagram_nodes, diagram_links, note=note)
    html += '<p><strong>Total known dissipation: ' + format(data['total_w'], '.8g') + ' W.</strong></p>'
    if data['zero_power']:
        html += '<p>Known zero-power sources (no ribbon): ' + escape(', '.join(data['zero_power'])) + '.</p>'
    if data['omitted']:
        html += '<details open><summary>Unknown / excluded sources (total incomplete)</summary><ul>'
        html += ''.join('<li>' + escape(item) + '</li>' for item in data['omitted']) + '</ul></details>'
    if links:
        html += '<details><summary>All known nonzero heat sources (W)</summary><table><tr><th>Source</th><th>W</th></tr>'
        html += ''.join('<tr><td>' + escape(labels[row['source']]) + '</td><td>' +
                        format(row['value'], '.12g') + '</td></tr>' for row in links)
        html += '</table></details>'
    return html


def write_sankey(path, bundle):
    """Publish source accounting with the normal report source/overwrite checks."""
    from wayricad_runtime.report_ui import checked_sources, publish_documents
    path = Path(path).with_suffix('.html')
    document = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>QuickTherm dissipation</title>'
                '<style>body{font:15px system-ui;margin:24px}</style><body>' +
                thermal_sankey_html(bundle) + '</body></html>')
    publish_documents({path: document}, sources=checked_sources(bundle))
    return path
