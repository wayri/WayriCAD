"""Numerical acceptance for the homogeneous two-PEC-plane cross section.

Reference: S. B. Cohn, "Shielded Coupled-Strip Transmission Line",
IRE Transactions on Microwave Theory and Techniques 3(5), 29–38 (1955),
equations 2–7. The same zero-thickness elliptic equations are documented in
KiCad's official common/transline_calculations/coupled_stripline.cpp:
https://github.com/KiCad/kicad-source-mirror/blob/master/common/transline_calculations/coupled_stripline.cpp
These tests evaluate those equations independently via the AGM. No production
solver code is used for the reference elliptic capacitances.
"""
import math
import unittest

from signal_integrity_advisor_plugin import coupled_stripline as strip
from signal_integrity_advisor_plugin.crosstalk import coupled_modes, _panel_log_distance


def elliptic_k(modulus):
    a, b = 1., math.sqrt((1 - modulus) * (1 + modulus))
    for _ in range(30):
        a, b = (a + b) / 2, math.sqrt(a * b)
    return math.pi / (2 * a)


def cohn_modal_capacitances(width, gap, plane_separation, er):
    a = math.tanh(math.pi * width / (2 * plane_separation))
    b = math.tanh(math.pi * (width + gap) / (2 * plane_separation))
    return tuple(4 * strip.EPS0 * er * elliptic_k(k) /
                 elliptic_k(math.sqrt((1 - k) * (1 + k))) for k in (a * b, a / b))


class TwoPlaneKernelTests(unittest.TestCase):
    def test_point_kernel_against_independent_eigenfunction_series(self):
        # Separated x coordinates make the Fourier eigenfunction sum rapidly
        # convergent; this does not use the logarithmic image expression.
        for point, source in (((.31, .2), (0., .7)), ((.8, .05), (0., .95)),
                              ((3., .4), (0., .15))):
            dx = abs(point[0] - source[0])
            reference = sum(math.sin(n * math.pi * point[1]) *
                            math.sin(n * math.pi * source[1]) *
                            math.exp(-n * math.pi * dx) / (n * math.pi)
                            for n in range(1, 201))
            self.assertAlmostEqual(strip._green(point, source), reference, places=14)
            self.assertAlmostEqual(strip._green(source, point), reference, places=14)

    def test_integrated_self_kernel_against_independent_image_series(self):
        # Exact line-panel logarithmic integrals over reflected image charges.
        # Symmetric image truncation has leading 1/(N+1/2) tail; eliminate it
        # with two truncations rather than treating a short sum as ground truth.
        for point, panel in (((.3, .24), ((.1, .24), (.5, .24))),
                             ((.1, .35), ((.1, .2), (.1, .5)))):
            def images(count):
                value = 0.
                for n in range(-count, count + 1):
                    positive = tuple((x, y + 2 * n) for x, y in panel)
                    negative = tuple((x, -y + 2 * n) for x, y in panel)
                    value += (_panel_log_distance(point, negative) -
                              _panel_log_distance(point, positive)) / (2 * math.pi)
                return value
            a, b = images(250), images(500)
            reference = ((500.5 * b) - (250.5 * a)) / 250
            self.assertAlmostEqual(strip._panel_green(point, panel), reference, delta=2e-9)

    def test_plane_boundaries_and_large_horizontal_separation(self):
        for y in (0., 1.):
            self.assertAlmostEqual(strip._green((.2, y), (0., .3)), 0., delta=1e-16)
        self.assertEqual(strip._green((1000., .3), (0., .4)), 0.)


class CoupledStriplineTests(unittest.TestCase):
    def test_centered_modes_against_cohn_elliptic_solution(self):
        # Includes both limits of the accepted width range and the tightest gap.
        for width, gap in ((.1, .1), (.5, .1), (1., .1), (1., 1.),
                           (3., .1), (10., .1), (1., 10.)):
            with self.subTest(width=width, gap=gap):
                # Check raw modal mathematics here; the public convergence gate
                # separately rejects cases whose much smaller difference has
                # not converged even when both capacitances match this reference.
                actual = strip._modal_capacitances(width, gap, 1., 1., 0., 4., 32)
                reference = cohn_modal_capacitances(width, gap, 2., 4.)
                for calculated, expected in zip(actual, reference):
                    self.assertLess(abs(calculated / expected - 1), .006)

    def test_near_and_mid_coupling_against_elliptic_difference(self):
        for gap in (.1, 1.):
            with self.subTest(gap=gap):
                actual = strip.coupled_stripline_modes(1., gap, 1., 1., 4.)
                ce, co = cohn_modal_capacitances(1., gap, 2., 4.)
                reference = (co - ce) / (co + ce)
                self.assertLess(abs(actual["coupling"] / reference - 1), .005)
                self.assertLessEqual(actual["coupling_refinement_relative"], .02)
                self.assertEqual(actual["coupling_numerical_status"], "RESOLVED")

    def test_coupling_alone_requires_additional_refinement(self):
        args = (3., .3, 1., 1., .035, 4.)
        coarse = strip._modal_capacitances(*args, 8)
        fine = strip._modal_capacitances(*args, 16)
        self.assertLess(max(abs(a / b - 1) for a, b in zip(coarse, fine)), .005)
        actual = strip.coupled_stripline_modes(3., .3, 1., 1., 4., .035)
        self.assertEqual(actual["panels_per_horizontal_face"], 32)
        self.assertLessEqual(actual["coupling_refinement_relative"], .02)

    def test_unconverged_coupling_is_rejected_even_when_modes_converge(self):
        coarse = strip._modal_capacitances(10., .1, 1., 1., 0., 4., 16)
        fine = strip._modal_capacitances(10., .1, 1., 1., 0., 4., 32)
        self.assertLess(max(abs(a / b - 1) for a, b in zip(coarse, fine)), .02)
        with self.assertRaisesRegex(ValueError, "coupling failed convergence"):
            strip.coupled_stripline_modes(10., .1, 1., 1., 4.)

    def test_marble_weak_coupling_has_its_own_verified_refinement(self):
        args = (.127, .673, .122954, .122954, 4.5, .035)
        actual = strip.coupled_stripline_modes(*args)
        ce, co = strip._modal_capacitances(.127, .673, .122954, .122954, .035, 4.5, 64)
        reference = (co - ce) / (co + ce)
        self.assertLess(abs(actual["coupling"] / reference - 1), .002)
        self.assertLess(actual["coupling_refinement_relative"], .005)
        self.assertGreater(actual["panel_refinement_relative"], actual["coupling"])
        self.assertAlmostEqual(actual["coupling_refinement_absolute"],
                               actual["coupling"] * actual["coupling_refinement_relative"])

    def test_far_coupling_reports_absolute_floor_and_no_relative_precision(self):
        actual = strip.coupled_stripline_modes(.127, 2., .122954, .122954, 4.5, .035)
        self.assertLess(actual["coupling"], actual["coupling_numerical_floor"])
        self.assertLessEqual(actual["coupling_refinement_absolute"], actual["coupling_numerical_floor"])
        self.assertIsNone(actual["coupling_refinement_relative"])
        self.assertEqual(actual["coupling_numerical_status"], "BELOW_NUMERICAL_FLOOR")
        ce, co = strip._modal_capacitances(.127, 2., .122954, .122954, .035, 4.5, 64)
        self.assertLess(abs(actual["coupling"] - (co - ce) / (co + ce)),
                        actual["coupling_numerical_floor"])

    def test_large_gap_recovers_single_centered_stripline(self):
        value = strip.coupled_stripline_modes(.5, 30., 1., 1., 4.)
        k = math.tanh(math.pi * .5 / 4)
        expected = 4 * strip.EPS0 * 4 * elliptic_k(k) / elliptic_k(math.sqrt(1 - k * k))
        self.assertLess(abs(value["c_even_pf_m"] * 1e-12 / expected - 1), .002)
        self.assertLess(value["coupling"], 1e-12)

    def test_asymmetric_stack_plane_swap_scale_and_dielectric_invariance(self):
        base = strip.coupled_stripline_modes(.3, .2, .2, .4, 4., .035)
        swapped = strip.coupled_stripline_modes(.3, .2, .4, .2, 4., .035)
        scaled = strip.coupled_stripline_modes(3., 2., 2., 4., 4., .35)
        air = strip.coupled_stripline_modes(.3, .2, .2, .4, 1., .035)
        for mode in ("even", "odd"):
            z, c, l = "z_" + mode + "_ohm", "c_" + mode + "_pf_m", "l_" + mode + "_nh_m"
            self.assertAlmostEqual(base[z], swapped[z], places=10)
            self.assertAlmostEqual(base[z], scaled[z], places=10)
            self.assertAlmostEqual(base[z] * 2, air[z], places=10)
            self.assertAlmostEqual(base[c] / 4, air[c], places=10)
            self.assertAlmostEqual(base[l], air[l], places=10)
            self.assertAlmostEqual(base[c] * 1e-12 * base[l] * 1e-9,
                                   4 / (strip.C_MM_NS * 1e6) ** 2, delta=1e-28)

    def test_distant_second_plane_recovers_single_plane(self):
        for thickness in (0., .035):
            a = strip.coupled_stripline_modes(.3, .2, .2, 200., 4., thickness)
            b = coupled_modes(.3, .2, .2, 4., thickness)
            for key in ("z_even_ohm", "z_odd_ohm"):
                self.assertLess(abs(a[key] / b[key] - 1), 1e-5)

    def test_finite_thickness_thin_limit_and_refinement(self):
        thin = strip.coupled_stripline_modes(.3, .2, .2, .4, 4., 1e-5)
        sheet = strip.coupled_stripline_modes(.3, .2, .2, .4, 4.)
        for mode in ("even", "odd"):
            self.assertLess(abs(thin["z_" + mode + "_ohm"] /
                                sheet["z_" + mode + "_ohm"] - 1), .003)
        # Independent extra resolution for an off-centre finite rectangle.
        ordinary = strip.coupled_stripline_modes(.3, .2, .2, .4, 4., .035)
        refined = strip._modal_capacitances(.3, .2, .2, .4, .035, 4., 64)
        for key, expected in zip(("c_even_pf_m", "c_odd_pf_m"), refined):
            self.assertLess(abs(ordinary[key] * 1e-12 / expected - 1), .002)
        self.assertLess(ordinary["z_even_ohm"], sheet["z_even_ohm"])
        self.assertLess(ordinary["z_odd_ohm"], sheet["z_odd_ohm"])

    def test_invalid_geometry_is_rejected(self):
        for args in ((0., .2, .2, .4, 4.), (.3, 0., .2, .4, 4.),
                     (.3, .2, 0., .4, 4.), (.3, .2, .2, .4, .9),
                     (.3, .2, .2, .4, 4., True), (.3, .2, .2, .4, 4., -.01),
                     (.5, .2, .2, .4, 4., .4), (.3, .2, .2, .4, 4., float("nan")),
                     (.3, .2, .2, .4, 4., ".035")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                strip.coupled_stripline_modes(*args)


if __name__ == "__main__":
    unittest.main()
