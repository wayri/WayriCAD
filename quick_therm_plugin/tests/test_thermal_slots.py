"""Independent geometry and heat-conservation checks for plated obround slots."""
import math
import unittest
try:
    import pcbnew
except ImportError:
    pcbnew = None
from quick_therm_plugin.thermal_drills import barrel_area_mm2, drill_wall_distance
from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal, _drill_at
from test_thermal_multilayer import inputs


class ThermalSlotTests(unittest.TestCase):
    def slot(self, angle=0):
        return {"id": "slot", "x_mm": 6., "y_mm": 6., "drill_mm": 1.,
                "drill_size_mm": [3.6, 1.], "drill_angle_deg": angle,
                "span_layers": [0, 31], "contact_layers": [0, 31],
                "outer_diameters_mm": {"0": 2., "31": 2.}}

    def test_wall_area_matches_independent_outer_minus_inner_capsules(self):
        def capsule_area(a, b):
            return b*(a-b) + math.pi*b*b/4
        for a, b, t in [(3.6, 1., .025), (1., 3.6, .025), (.3, .3, .02)]:
            slot = self.slot(); slot["drill_size_mm"] = [a, b]
            expected = capsule_area(max(a,b)+2*t, min(a,b)+2*t) - capsule_area(max(a,b), min(a,b))
            self.assertAlmostEqual(barrel_area_mm2(slot,t), expected, places=14)
            # kA/L: an isothermal 10 K difference through a 1.6mm barrel.
            conductance = 385 * expected * 1e-6 / .0016
            self.assertAlmostEqual(10*conductance, 10*385*barrel_area_mm2(slot,t)/1600, places=12)

    def test_saved_kicad_rotation_and_void_exclusion(self):
        slot = self.slot(30)
        # Native KiCad positive30deg pad rotation has long-axis negative30deg
        # in board XY coordinates, whose Y direction is downward.
        tip = (6 + 1.6*math.cos(math.pi/6), 6 - 1.6*math.sin(math.pi/6))
        self.assertLess(drill_wall_distance(tip, slot), 0)
        self.assertEqual(_drill_at(tip, 0, {"barrels":[slot]}), "slot")
        self.assertGreater(drill_wall_distance((6.,7.),slot), 0)
        slot["drill_size_mm"] = [1.,3.6]
        self.assertLess(drill_wall_distance((6.8,7.386),slot), 0)

    def test_plated_slot_solve_preserves_heat_and_uses_distributed_land(self):
        geometry, view, result, settings = inputs()
        slot = self.slot()
        polygon = {"outer": [[3.8,4.8],[8.2,4.8],[8.2,7.2],[3.8,7.2]], "holes": []}
        slot["land_polygons_mm"] = {"0": [polygon], "31": [polygon]}
        geometry["barrels"] = [slot]
        settings.update(board_h_w_m2k=15, board_emissivity=0)
        for grid in (24,48):
            settings["grid_cells_long_axis"] = grid
            solved = solve_multilayer_thermal(geometry,view,result,settings)
            self.assertLess(abs(solved["heat_balance"]["residual_w"]),1e-6)
            self.assertGreater(solved["mesh"]["barrel_stencil_edges"],1)
            self.assertEqual(solved["mesh"]["unresolved_barrel_stencils"],0)

    def test_no_single_circular_node_for_slot(self):
        geometry,view,result,settings=inputs();geometry["barrels"]=[self.slot()]
        settings["barrel_contact_mode"]="nearest_cell"
        with self.assertRaisesRegex(ValueError,"distributed"):
            solve_multilayer_thermal(geometry,view,result,settings)


    @unittest.skipIf(pcbnew is None, "Requires native KiCad drill polygons")
    def test_rotated_capsule_matches_native_kicad_hole(self):
        from quick_therm_plugin.board_geometry import _hole, _polygons
        board = pcbnew.BOARD(); footprint = pcbnew.FOOTPRINT(board)
        pad = pcbnew.PAD(footprint)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(4), pcbnew.FromMM(2)))
        pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(3.6), pcbnew.FromMM(1)))
        pad.SetDrillShape(pcbnew.PAD_DRILL_SHAPE_OBLONG)
        pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(6), pcbnew.FromMM(6)))
        for angle in (0, 30, 90, 145):
            pad.SetOrientationDegrees(angle)
            polygons = _polygons(_hole(pcbnew,pad,pcbnew.FromMM(.005)),pcbnew)
            self.assertTrue(polygons)
            for point in polygons[0]["outer"]:
                self.assertLess(abs(drill_wall_distance(point,self.slot(angle))),.006)
