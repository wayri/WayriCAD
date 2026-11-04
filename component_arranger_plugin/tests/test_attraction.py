"""Saved-wire attraction binds real PCB pins and respects placement constraints."""
from dataclasses import replace
import math
import unittest

from component_arranger_plugin import attraction, engine as e


def part(key, x=0, y=0, width=1, **kwargs):
    courtyard = ((-width/2, -.5), (width/2, -.5),
                 (width/2, .5), (-width/2, .5))
    return e.Footprint(key, key, x, y, courtyards=(courtyard,), **kwargs)


def link(a, ap, b, bp, length, sheet='/sheet'):
    return dict(kind='drawn_wire', from_reference=a, from_pin=ap,
                from_symbol=sheet+'/'+a, to_reference=b, to_pin=bp,
                to_symbol=sheet+'/'+b, length_mm=length)


def metadata(refs, links):
    return dict(symbols=[dict(reference=ref, sheet_path='/sheet',id='/sheet/'+ref) for ref in refs],
                pin_links=links)


class AttractionTests(unittest.TestCase):
    def test_shorter_wire_stronger_and_zero_length_finite(self):
        fps = tuple(part(ref, pads=(e.Pad('1', 'N', 0, 0),)) for ref in ('A', 'B', 'C', 'D'))
        springs, warnings = attraction.bind(fps, metadata('ABCD',
            [link('A', '1', 'B', '1', 0), link('C', '1', 'D', '1', 10)]))
        self.assertFalse(warnings)
        self.assertEqual(len(springs), 2)
        self.assertTrue(math.isfinite(springs[0]['weight']))
        self.assertGreater(springs[0]['weight'], springs[1]['weight'])

    def test_wrong_net_and_ambiguous_sheet_are_omitted_with_warning(self):
        a = part('A', pads=(e.Pad('1', 'N', 0, 0),))
        b = part('B', pads=(e.Pad('1', 'OTHER', 0, 0),))
        meta = metadata('AB', [link('A', '1', 'B', '1', 1)])
        springs, warnings = attraction.bind((a, b), meta)
        self.assertEqual(springs, ())
        self.assertTrue(warnings)
        b = replace(b, pads=(e.Pad('1', 'N', 0, 0),))
        meta['symbols'].append(dict(reference='A', sheet_path='/other'))
        springs, warnings = attraction.bind((a, b), meta)
        self.assertEqual(springs, ())
        self.assertTrue(warnings)
        meta['symbols'].pop()
        springs, warnings = attraction.bind((a, b), meta, {'A':'/sheet/A', 'B':'/sheet/B'})
        self.assertEqual(len(springs), 1)
        self.assertFalse(warnings)
        self.assertEqual((springs[0]['from_pin'], springs[0]['to_pin'], springs[0]['net']), ('1', '1', 'N'))

    def test_fanout_normalization_bounds_total_power_net_weight(self):
        for count in (2, 16):
            refs = ['U'] + [f'R{i}' for i in range(count)]
            fps = tuple(part(ref, pads=(e.Pad('1', 'VDD', 0, 0),)) for ref in refs)
            springs, warnings = attraction.bind(fps, metadata(refs,
                [link('U', '1', ref, '1', 0) for ref in refs[1:]]))
            self.assertFalse(warnings)
            self.assertEqual(len(springs), count)
            self.assertLessEqual(sum(s['weight'] for s in springs), 1.0 + 1e-12)

    def test_replaced_symbol_or_duplicate_reference_is_not_a_pin_identity(self):
        fps=tuple(part(ref,pads=(e.Pad('1','N',0,0),)) for ref in ('A','B'))
        meta=metadata('AB',[link('A','1','B','1',1)])
        springs,warnings=attraction.bind(fps,meta,{'A':'/sheet/old-A','B':'/sheet/B'})
        self.assertFalse(springs);self.assertTrue(warnings)
        meta['symbols'].append(dict(reference='A',sheet_path='/sheet',id='/sheet/duplicate'))
        for paths in ({},{'A':'/sheet/A','B':'/sheet/B'}):
            springs,warnings=attraction.bind(fps,meta,paths)
            self.assertFalse(springs);self.assertTrue(warnings)

    def test_verified_units_have_external_springs_without_self_attraction(self):
        fps=(part('U',pads=(e.Pad('1','N',0,0),e.Pad('2','N',1,0))),
             part('R',pads=(e.Pad('1','N',0,0),)))
        internal=link('U','1','U','2',2);internal['to_symbol']='/sheet/U2'
        external=link('U','2','R','1',4);external['from_symbol']='/sheet/U2'
        meta=metadata(('U','R'),[internal,external])
        meta['symbols'][0].update(unit=1,lib_id='Logic:Dual')
        meta['symbols'].append(dict(reference='U',sheet_path='/sheet',id='/sheet/U2',
                                    unit=2,lib_id='Logic:Dual'))
        springs,warnings=attraction.bind(fps,meta,{'U':'/sheet/U','R':'/sheet/R'})
        self.assertFalse(warnings);self.assertEqual(len(springs),1)
        attraction.validate(fps,springs,1)
        self.assertNotEqual(springs[0]['from_key'],springs[0]['to_key'])

    def test_metrics_use_transformed_pin_positions(self):
        a = part('A', 10, 20, angle=90, side='bottom', pads=(e.Pad('1', 'N', 1, 2),))
        b = part('B', 8, 23, pads=(e.Pad('1', 'N', 0, 0),))
        springs, _ = attraction.bind((a, b), metadata('AB', [link('A', '1', 'B', '1', 0)]))
        settings = e.Settings('A', (0, 0, 30, 30), pin_springs=springs, attraction_strength=2)
        m = e.metrics((a, b), settings)
        self.assertAlmostEqual(m.spring_length_mm, 4)
        self.assertAlmostEqual(m.spring_energy_mm, 16)
        self.assertEqual(m.springs, 1)

    def test_invalid_springs_and_strength_rejected(self):
        fps = (part('A', pads=(e.Pad('1', 'N', 0, 0),)),
               part('B', 3, pads=(e.Pad('1', 'N', 0, 0),)))
        springs, _ = attraction.bind(fps, metadata('AB', [link('A', '1', 'B', '1', 1)]))
        settings = e.Settings('A', (-5, -5, 5, 5), pin_springs=springs)
        for strength in (-1, 11, math.nan, math.inf, True):
            with self.subTest(strength=strength), self.assertRaises(ValueError):
                e.arrange(fps, replace(settings, attraction_strength=strength))
        for changes in (dict(weight=0), dict(weight=math.nan), dict(weight=1.1),
                        dict(weight=True), dict(wire_length_mm=-1), dict(to_pin='missing'),
                        dict(net='OTHER'), dict(to_key='A')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                e.arrange(fps, replace(settings, pin_springs=({**springs[0], **changes},)))

    def test_arrangement_attracts_parts_to_respective_pins(self):
        anchor = part('U', width=8, pads=(e.Pad('1', 'N', -3, 0), e.Pad('2', 'N', 3, 0)))
        left = part('L', -6, 5, pads=(e.Pad('1', 'N', 0, 0),))
        right = part('R', 6, 5, pads=(e.Pad('1', 'N', 0, 0),))
        fps = (anchor, left, right)
        springs, _ = attraction.bind(fps, metadata(('U', 'L', 'R'),
            [link('U', '1', 'L', '1', 0), link('U', '2', 'R', '1', 0)]))
        settings = e.Settings('U', (-8, -6, 8, 7), pin_springs=springs,
                              attraction_strength=10, max_candidates=1200, grid_mm=1)
        guided = e.arrange(fps, settings)
        unguided = e.arrange(fps, replace(settings, attraction_strength=0))
        self.assertTrue(guided.complete, guided.warnings)
        self.assertTrue(unguided.complete, unguided.warnings)
        self.assertEqual(guided.footprints[0], anchor)
        self.assertTrue(all(e.legal(p, guided.footprints, settings) for p in guided.footprints))
        guided_distance = attraction.measure(guided.footprints, springs, 1, e.transform)[1]
        unguided_distance = attraction.measure(unguided.footprints, springs, 1, e.transform)[1]
        self.assertLess(guided_distance, unguided_distance)
        self.assertLess(guided.footprints[1].x, 0)
        self.assertGreater(guided.footprints[2].x, 0)


if __name__ == '__main__':
    unittest.main()
