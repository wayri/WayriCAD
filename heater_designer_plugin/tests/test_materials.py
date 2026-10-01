import unittest

from heater_designer_plugin.materials import (
    MATERIALS, Material, custom_bulk, custom_sheet, resistance_factor,
    segment_resistance_ohm,
)


class MaterialTests(unittest.TestCase):
    def test_straight_copper_and_series_sum(self):
        copper = MATERIALS["copper"]
        expected = 1.724e-8 * .1 / (.001 * 35e-6)
        self.assertAlmostEqual(segment_resistance_ohm(copper, 100, 1, 35), expected)
        self.assertAlmostEqual(sum(segment_resistance_ohm(copper, 25, 1, 35)
                                   for _ in range(4)), expected)

    def test_copper_temperature(self):
        self.assertAlmostEqual(resistance_factor(MATERIALS["copper"], 120), 1.393)
        with self.assertRaises(ValueError):
            resistance_factor(MATERIALS["copper"], 250)

    def test_film_squares_and_bulk_equivalence(self):
        sheet = custom_sheet(10, .001)
        self.assertAlmostEqual(segment_resistance_ohm(sheet, 100, 2), 500)
        self.assertAlmostEqual(segment_resistance_ohm(sheet, 100, 2, temperature_c=120), 550)
        foil = custom_bulk(1e-6)
        self.assertAlmostEqual(segment_resistance_ohm(foil, 10, 2, 1),
                               segment_resistance_ohm(custom_sheet(1), 10, 2))

    def test_unknown_tcr_is_not_zero(self):
        for key in ("manganin", "constantan"):
            material = MATERIALS[key]
            self.assertEqual(resistance_factor(material), 1)
            with self.assertRaisesRegex(ValueError, "no unique TCR"):
                resistance_factor(material, 60)
        self.assertEqual(resistance_factor(custom_sheet(2, 0), 100), 1)

    def test_manufacturer_temperature_tables(self):
        self.assertAlmostEqual(resistance_factor(MATERIALS["nichrome80"], 150), 1.015)
        self.assertAlmostEqual(segment_resistance_ohm(MATERIALS["inconel600"], 1000, 1, 1000, 400), 1.09)
        for temperature in (0, 1300):
            with self.assertRaises(ValueError):
                resistance_factor(MATERIALS["nichrome80"], temperature)

    def test_invalid_inputs(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                custom_bulk(value)
            with self.assertRaises(ValueError):
                custom_sheet(value)
        with self.assertRaises(ValueError):
            custom_bulk(1e-6, float("nan"))
        with self.assertRaises(ValueError):
            Material("bad", "Bad", 1e-6, sheet_resistance_ohm_sq=1)
        for arguments in ((-1, 1, 35), (1, 0, 35), (1, 1, 0), (1, 1, None)):
            with self.assertRaises(ValueError):
                segment_resistance_ohm(MATERIALS["copper"], *arguments)
        with self.assertRaises(ValueError):
            resistance_factor(custom_bulk(1e-6, -.1), 40)


if __name__ == "__main__":
    unittest.main()
