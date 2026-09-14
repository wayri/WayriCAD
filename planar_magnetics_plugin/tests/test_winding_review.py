"""Native UI controller regression: geometry does not depend on motion inputs."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

try:
    import pcbnew
except ImportError:
    pcbnew=None


@unittest.skipIf(pcbnew is None,'Requires native KiCad Python')
class WindingReviewTests(unittest.TestCase):
    def test_small_winding_review_does_not_run_coupled_solver(self):
        from planar_magnetics_plugin.planar_magnetics_plugin import MagneticsFrame,MagneticsEngine
        from planar_magnetics_plugin.analysis import CoilSpec
        controller=SimpleNamespace(clear_preview=Mock(),
            _spec=lambda:CoilSpec(outer_width_mm=6,outer_height_mm=6,turns=3,
                                 trace_width_mm=.25,spacing_mm=.3,layers=2),
            catalog={},actuator=SimpleNamespace(GetStringSelection=lambda:'Linear solenoid'),
            _motion_spec=Mock(side_effect=AssertionError('Motion input is unrelated to winding preview')),
            preview=Mock(),motion_plot=Mock(),_fill_results=Mock(),tabs=Mock(),status=Mock(),guide=Mock())
        with patch.object(MagneticsEngine,'simulate_dynamics') as solver:
            MagneticsFrame._calculate(controller,0)
        solver.assert_not_called()
        self.assertGreater(len(controller.result.segments),0)
        self.assertIsNone(controller.result.dynamics)
        controller.preview.show_result.assert_called_once_with(controller.result)
        controller.tabs.SetSelection.assert_called_once_with(0)

    def test_explicit_motion_still_reports_solver_limits(self):
        from planar_magnetics_plugin.planar_magnetics_plugin import MagneticsFrame,MagneticsEngine
        from planar_magnetics_plugin.analysis import CoilSpec,MotionSpec
        controller=SimpleNamespace(clear_preview=Mock(),_spec=lambda:CoilSpec(),catalog={},
            actuator=SimpleNamespace(GetStringSelection=lambda:'Linear solenoid'),_motion_spec=lambda:MotionSpec())
        with patch.object(MagneticsEngine,'simulate_dynamics',side_effect=ValueError('integration limit')):
            with self.assertRaisesRegex(ValueError,'integration limit'):
                MagneticsFrame._calculate(controller,2)


if __name__=='__main__':unittest.main()
