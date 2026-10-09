"""Physical board-cell coverage, distinct from partial junction interpolation."""
import copy
import unittest

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import Normalize
from matplotlib.figure import Figure

from wayricad_runtime.thermal_field import draw_field, field_available
from quick_therm_plugin.thermal_network import solve_thermal_network
from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal
from quick_therm_plugin.tests.test_thermal_network import view, result, settings
from quick_therm_plugin.tests.test_thermal_multilayer import inputs


def field(values=None):
    return {"value_location": "finite_volume_cell",
            "x_centers_mm": [.5, 1.5, 2.5, 3.5, 4.5],
            "y_centers_mm": [.5, 1.5, 2.5, 3.5, 4.5],
            "x_edges_mm": [0, 1, 2, 3, 4, 5], "y_edges_mm": [0, 1, 2, 3, 4, 5],
            "values_c": values if values is not None else [[30.] * 5 for _ in range(5)]}


def render(samples, outline=None):
    figure = Figure(figsize=(5, 5), dpi=100)
    canvas = FigureCanvasAgg(figure)
    ax = figure.add_subplot(111)
    draw_field(ax, samples, outline or [], Normalize(20, 40))
    ax.set_xlim(-.5, 5.5); ax.set_ylim(5.5, -.5)
    canvas.draw()
    return canvas, ax


def pixel(canvas, ax, x, y):
    xp, yp = ax.transData.transform((x, y))
    pixels = np.asarray(canvas.buffer_rgba())
    return pixels[pixels.shape[0] - 1 - round(yp), round(xp), :3]


class PhysicalFieldBoundaryTests(unittest.TestCase):
    def test_known_boundary_cells_reach_mesh_edges_before_and_after_zoom(self):
        samples = field(); original = copy.deepcopy(samples)
        canvas, ax = render(samples)
        for x, y in ((.1, .1), (4.9, .1), (.1, 4.9), (4.9, 4.9)):
            self.assertFalse(np.array_equal(pixel(canvas, ax, x, y), [255] * 3))
        np.testing.assert_array_equal(pixel(canvas, ax, -.2, 2), [255] * 3)
        ax.set_xlim(-.1, .8); ax.set_ylim(.8, -.1); canvas.draw()
        self.assertFalse(np.array_equal(pixel(canvas, ax, .05, .05), [255] * 3))
        self.assertEqual(samples, original)

    def test_missing_cells_are_not_filled_by_cell_support_or_smoothing(self):
        samples = field(); samples["values_c"][2][2] = None
        canvas, ax = render(samples)
        for x, y in ((2.1, 2.1), (2.9, 2.9), (2.5, 2.5)):
            np.testing.assert_array_equal(pixel(canvas, ax, x, y), [255] * 3)
        self.assertFalse(np.array_equal(pixel(canvas, ax, 1.9, 2.5), [255] * 3))

    def test_known_isolated_physical_cell_is_visible_without_claiming_interpolation(self):
        samples = field([[None] * 5 for _ in range(5)])
        samples["values_c"][0][0] = 30
        self.assertTrue(field_available(samples))
        canvas, ax = render(samples)
        self.assertFalse(np.array_equal(pixel(canvas, ax, .1, .1), [255] * 3))
        np.testing.assert_array_equal(pixel(canvas, ax, 1.1, .5), [255] * 3)
        self.assertEqual(len(ax.collections), 1)  # Cell area, no smooth quad.

    def test_cell_underlay_clips_small_cutout_and_disjoint_outlines(self):
        outline = [
            {"outer_mm": [[0, 0], [2, 0], [2, 5], [0, 5]],
             "holes_mm": [[[.7, .7], [.9, .7], [.9, .9], [.7, .9]]]},
            {"outer_mm": [[3, 0], [5, 0], [5, 5], [3, 5]], "holes_mm": []}]
        canvas, ax = render(field(), outline)
        for x, y in ((.8, .8), (2.5, 2.5)):
            np.testing.assert_array_equal(pixel(canvas, ax, x, y), [255] * 3)
        for x, y in ((.1, 2), (4.9, 2)):
            self.assertFalse(np.array_equal(pixel(canvas, ax, x, y), [255] * 3))

    def test_point_samples_and_invalid_cell_metadata_do_not_gain_area(self):
        for mutate in (lambda data: data.pop("value_location"),
                       lambda data: data.update(x_edges_mm=[0, 1, 2, 2, 4, 5]),
                       lambda data: data.update(x_edges_mm=[0, 1, 2])):
            with self.subTest(mutate=mutate):
                samples = field(); mutate(samples)
                canvas, ax = render(samples)
                np.testing.assert_array_equal(pixel(canvas, ax, .1, .1), [255] * 3)
                self.assertFalse(np.array_equal(pixel(canvas, ax, 2, 2), [255] * 3))

    def test_thin_sheet_solves_whole_board_outside_four_central_sources(self):
        board = view(); powers = result()
        board["components"] = [{"reference": f"U{i}", "position_mm": [x, y],
                                "bbox_mm": [x-2, y-2, x+2, y+2],
                                "side": "top", "on_board": True}
                               for i, (x, y) in enumerate(((35, 35), (65, 35),
                                                          (65, 65), (35, 65)), 1)]
        powers["components"] = [{"reference": f"U{i}", "power_w": .25, "heat_path": "board"}
                                for i in range(1, 5)]
        solved = solve_thermal_network(board, powers, settings())
        samples = solved["board_field"]
        self.assertEqual(samples["value_location"], "finite_volume_cell")
        self.assertEqual(samples["active_cells"], 64)
        self.assertEqual(samples["x_edges_mm"][::8], [0, 100])
        self.assertEqual(samples["y_edges_mm"][::8], [0, 100])
        for j, i in ((0, 0), (0, 7), (7, 0), (7, 7)):
            self.assertGreater(samples["values_c"][j][i], 25)
        self.assertAlmostEqual(solved["heat_balance"]["input_w"], 1)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-5)

    def test_thin_sheet_keeps_concave_notch_and_cutout_unknown(self):
        board = view(); powers = result()
        board["outline"] = [{"outer_mm": [[0, 0], [100, 0], [100, 50],
                                            [50, 50], [50, 100], [0, 100]],
                              "holes_mm": [[[10, 10], [22, 10], [22, 22], [10, 22]]]}]
        board["components"] = [{"reference": "U1", "position_mm": [30, 30],
                                "bbox_mm": [28, 28, 32, 32], "side": "top", "on_board": True}]
        powers["components"] = [{"reference": "U1", "power_w": 1, "heat_path": "board"}]
        solved = solve_thermal_network(board, powers, settings())
        values = solved["board_field"]["values_c"]
        self.assertIsNone(values[1][1])  # Through cutout.
        self.assertIsNone(values[7][7])  # Concave notch.
        self.assertGreater(values[0][7], 25)
        self.assertGreater(values[7][0], 25)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-5)

    def test_layered_cells_cover_both_complete_board_faces(self):
        geometry, board, powers, material = inputs()
        solved = solve_multilayer_thermal(geometry, board, powers, material)
        for samples in solved["layers"]:
            self.assertEqual(samples["value_location"], "finite_volume_cell")
            self.assertEqual(samples["x_edges_mm"][::24], [0, 12])
            self.assertEqual(samples["y_edges_mm"][::24], [0, 12])
            self.assertEqual(sum(value is not None for row in samples["values_c"] for value in row), 576)
            self.assertGreater(samples["values_c"][0][0], 20)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-6)
