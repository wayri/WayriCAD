"""Shared power diagrams preserve accounting, scale and unsafe labels."""
import math
import unittest
import xml.etree.ElementTree as ET

from wayricad_runtime.sankey import layout_sankey, sankey_html, sankey_svg


class SankeyTests(unittest.TestCase):
    def test_split_and_merge_use_one_scale(self):
        nodes = [dict(id=name, label=name) for name in ('source', 'load', 'loss', 'total')]
        links = [dict(source='source', target='load', value=9),
                 dict(source='source', target='loss', value=1),
                 dict(source='load', target='total', value=9),
                 dict(source='loss', target='total', value=1)]
        layout = layout_sankey(nodes, links)
        self.assertAlmostEqual(layout['links'][0]['thickness']/layout['links'][1]['thickness'], 9)
        by_id = {node['id']: node for node in layout['nodes']}
        self.assertEqual(by_id['total']['incoming'], 10)
        for edge in layout['links']:
            self.assertLess(edge['x1'], edge['x2'])
            self.assertLessEqual(edge['y1']+edge['thickness'], by_id[edge['source']]['y']+by_id[edge['source']]['height'])
        ET.fromstring(sankey_svg('Power', layout))
        self.assertEqual(links[0]['value'], 9)

    def test_invalid_graphs_and_values_are_not_drawn(self):
        nodes = [dict(id='a', label='A'), dict(id='b', label='B')]
        for value in (-1, math.nan, math.inf, True, '3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                layout_sankey(nodes, [dict(source='a', target='b', value=value)])
        for links in ([dict(source='a', target='a', value=1)],
                      [dict(source='a', target='b', value=1), dict(source='b', target='a', value=1)],
                      [dict(source='a', target='unknown', value=1)]):
            with self.assertRaises(ValueError):
                layout_sankey(nodes, links)
        with self.assertRaises(ValueError):
            layout_sankey(nodes+nodes, [])

    def test_unknown_empty_zero_and_unbalanced_evidence_stays_explicit(self):
        self.assertIn('No quantified power flows', sankey_html('Power', [], [], 'Unknown source'))
        nodes = [dict(id=name, label=name) for name in ('a', 'b', 'c')]
        layout = layout_sankey(nodes, [dict(source='a', target='b', value=10), dict(source='b', target='c', value=8)])
        self.assertEqual(layout['nodes'][1]['incoming'], 10)
        self.assertEqual(layout['nodes'][1]['outgoing'], 8)
        self.assertIn('0 W', sankey_html('Zero', nodes, [dict(source='a', target='b', value=0)]))

    def test_labels_are_escaped_and_offline_svg_survives_without_script(self):
        label = '</script><img src=x onerror=alert(1)> & "'
        result = sankey_html(label, [dict(id='a', label=label), dict(id='b', label='total')],
                             [dict(source='a', target='b', value=.125)], label)
        self.assertNotIn('<img', result)
        self.assertNotIn('<script src=', result)
        self.assertIn('0.125 W', result)
        self.assertIn('tabindex="0"', result)
        self.assertIn('Exact power flows', result)

    def test_many_parts_do_not_overlap_or_hide_tiny_flow(self):
        nodes = [dict(id=str(i), label='Part '+str(i)) for i in range(100)]+[dict(id='total', label='Total')]
        layout = layout_sankey(nodes, [dict(source=str(i), target='total', value=1e-12 if i == 0 else 1) for i in range(100)])
        column = layout['nodes'][:-1]
        self.assertTrue(all(b['y'] >= a['y']+a['height'] for a, b in zip(column, column[1:])))
        self.assertGreater(layout['links'][0]['thickness'], 0)
        self.assertEqual(len(layout['links']), 100)

    def test_extreme_finite_power_does_not_overflow_display_coordinates(self):
        nodes = [dict(id='a', label='A'), dict(id='b', label='B')]
        for value in (1e-320, 1e308):
            layout = layout_sankey(nodes, [dict(source='a', target='b', value=value)])
            self.assertTrue(math.isfinite(layout['links'][0]['thickness']))
            self.assertGreater(layout['links'][0]['thickness'], 0)


if __name__ == '__main__':
    unittest.main()
