"""Analytical RC, storage, time refinement and declared environment checks."""
import math
import unittest
import numpy as np
from scipy.sparse import csr_matrix
from quick_therm_plugin.thermal_spatial_transient import evolve
from quick_therm_plugin.thermal_environments import boundary_settings
from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal
from quick_therm_plugin.tests.test_thermal_multilayer import inputs

class SpatialTransientTests(unittest.TestCase):
    def run_rc(self,dt=.1, h=1, schedule=None):
        settings={"duration_s":10,"timestep_s":dt,"initial_c":20}
        if schedule: settings["power_schedules"]={"U1":schedule}
        return evolve(csr_matrix((1,1)),np.array([2.]),{"U1":np.array([3.])},
                      np.ones(1),np.array([h]),np.zeros(1),20,np.zeros(1),np.zeros(1),{},settings)
    def test_rc_analytical_and_time_refinement(self):
        exact=20+3*(1-math.exp(-5))
        coarse=self.run_rc(.5);fine=self.run_rc(.1)
        self.assertLess(abs(fine["final_temperatures_c"][0]-exact),.003)
        self.assertLess(abs(fine["final_temperatures_c"][0]-exact),abs(coarse["final_temperatures_c"][0]-exact))
        self.assertLess(fine["max_energy_residual_w"],1e-10)
    def test_adiabatic_storage(self):
        result=self.run_rc(h=0)
        self.assertAlmostEqual(result["final_temperatures_c"][0],35,places=9)
        self.assertAlmostEqual(sum(row["stored_energy_change_j"] for row in result["energy_balance"]),30,places=9)
    def test_power_schedule_cooling(self):
        result=self.run_rc(.1,schedule=[[0,1],[2,1],[2.01,0],[10,0]])
        self.assertLess(result["final_temperatures_c"][0],20.05)
    def test_two_node_conduction_conserves_storage(self):
        result=evolve(csr_matrix([[1.,-1.],[-1.,1.]]),np.array([1.,1.]),
            {"U1":np.array([2.,0.])},np.zeros(2),np.zeros(2),np.zeros(2),
            20,np.zeros(2),np.zeros(2),{}, {"duration_s":1,"timestep_s":.01})
        self.assertAlmostEqual(sum(result["final_temperatures_c"]),42,places=8)
        self.assertLess(result["max_energy_residual_w"],1e-9)
        # Mean rises linearly; difference follows dD/dt=2-2D.
        exact_difference=1-math.exp(-2)
        temperatures=result["final_temperatures_c"]
        self.assertAlmostEqual(temperatures[0]-temperatures[1],exact_difference,delta=.003)
    def test_radiation_energy_balance_and_refinement(self):
        def run(dt):
            return evolve(csr_matrix((1,1)),np.array([1.]),{"U1":np.array([5.])},
                np.array([.01]),np.zeros(1),np.array([.9]),20,np.zeros(1),np.zeros(1),
                {},{"duration_s":10,"timestep_s":dt})
        reference=run(.025);fine=run(.1);coarse=run(.5)
        self.assertLess(fine["max_energy_residual_w"],1e-8)
        self.assertLess(abs(fine["final_temperatures_c"][0]-reference["final_temperatures_c"][0]),
                        abs(coarse["final_temperatures_c"][0]-reference["final_temperatures_c"][0]))
    def test_unknown_source_and_missing_capacity_rejected(self):
        with self.assertRaises(ValueError): self.run_rc(schedule=[[0,-1]])
        with self.assertRaises(ValueError):
            evolve(csr_matrix((1,1)),[0],{"U1":np.ones(1)},np.ones(1),np.ones(1),np.zeros(1),20,np.zeros(1),np.zeros(1),{}, {"duration_s":1,"timestep_s":.1})
    def test_spatial_board_frames_and_balance(self):
        geometry,view,result,settings=inputs()
        settings.update(board_emissivity=0,board_h_w_m2k=20,
            transient_settings={"duration_s":2,"timestep_s":.5,
                "copper_volumetric_capacity_j_m3k":3.45e6,
                "dielectric_volumetric_capacity_j_m3k":1.8e6})
        solved=solve_multilayer_thermal(geometry,view,result,settings)
        transient=solved["transient"]
        self.assertEqual(len(transient["frames"]),5)
        self.assertLess(transient["max_energy_residual_w"],1e-8)
        self.assertLess(max(transient["final_temperatures_c"]),solved["layers"][0]["sampled_max_c"])
        self.assertEqual(transient["components"][0]["reference"],"U1")
    def test_environment_requires_declared_boundaries(self):
        for env in ("forced_air","potting","sealed"):
            with self.assertRaises((ValueError,KeyError)): boundary_settings(env,{})
        values,notes=boundary_settings("potting",{"potting_k_w_mk":1,"potting_thickness_mm":10,"potting_outer_h_w_m2k":10})
        self.assertAlmostEqual(values["board_h_w_m2k"],1/.11)
        self.assertEqual(values["board_emissivity"],0)
        self.assertTrue(notes)
        with self.assertRaises(ValueError): boundary_settings("vacuum",{"board_h_w_m2k":1})
    def test_expanded_environments_solve(self):
        configs={"forced_air":{"board_h_w_m2k":50},
                 "sealed":{"board_h_w_m2k":8,"enclosure_temperature_c":30},
                 "potting":{"potting_k_w_mk":1,"potting_thickness_mm":1,"potting_outer_h_w_m2k":10}}
        for env,config in configs.items():
            with self.subTest(env=env):
                geometry,view,result,settings=inputs(env)
                settings.update(config)
                solved=solve_multilayer_thermal(geometry,view,result,settings)
                self.assertEqual(solved["status"],"converged")
                self.assertLess(abs(solved["heat_balance"]["residual_w"]),1e-7)

    def test_linear_pulse_between_regular_samples_preserves_input_energy(self):
        schedule = [[0, 0], [.11, 0], [.12, 1], [.13, 0], [10, 0]]
        solved = self.run_rc(.5, h=0, schedule=schedule)
        # Area under this unit-height triangular pulse is exactly .01 s;
        # source=3 W and capacity=2 J/K. It must not vanish between samples.
        expected_energy = 3*.01
        self.assertAlmostEqual(solved['final_temperatures_c'][0], 20+expected_energy/2, 11)
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['energy_balance']), expected_energy, 12)
        self.assertEqual(solved['schedule_interpolation'], 'linear')
        actual_times = [row['time_s'] for row in solved['energy_balance']]
        for event in (.11, .12, .13):
            self.assertIn(event, actual_times)
        self.assertAlmostEqual(sum(row['elapsed_s'] for row in solved['energy_balance']), 10, 12)

    def test_linear_ramp_adiabatic_energy_is_independent_of_timestep(self):
        # P rises from 0 to 3 W over two seconds and remains at 3 W for eight.
        for dt in (.7, .1):
            solved = self.run_rc(dt, h=0, schedule=[[0, 0], [2, 1]])
            self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['energy_balance']), 27, 11)
            self.assertAlmostEqual(solved['final_temperatures_c'][0], 33.5, 10)

    def test_step_event_uses_old_power_before_event_and_new_power_after(self):
        solved = evolve(csr_matrix((1, 1)), [2], {'U1': [3]}, [1], [0], [0],
                        20, [0], [0], {}, {'duration_s': 1, 'timestep_s': .5,
                        'power_schedules': {'U1': [[0, 1], [.23, 0]]},
                        'schedule_interpolation': 'step'})
        rows = solved['energy_balance']
        self.assertEqual([row['time_s'] for row in rows], [.23, .5, 1.])
        self.assertEqual([row['input_w'] for row in rows], [3., 0., 0.])
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in rows), .69, 12)
        self.assertAlmostEqual(solved['final_temperatures_c'][0], 20+.69/2, 12)
        self.assertEqual(solved['schedule_interpolation'], 'step')

    def test_step_at_end_does_not_retroactively_remove_heat(self):
        solved = evolve(csr_matrix((1, 1)), [2], {'U1': [3]}, [1], [0], [0],
                        20, [0], [0], {}, {'duration_s': 1, 'timestep_s': .5,
                        'power_schedules': {'U1': [[0, 1], [1, 0]]},
                        'schedule_interpolation': 'step'})
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['energy_balance']), 3, 12)
        self.assertAlmostEqual(solved['final_temperatures_c'][0], 21.5, 12)

    def test_air_heating_then_cooling_refines_to_analytical_event_solution(self):
        # C=2 J/K, h*A=1 W/K and P=3 W until t=.23 s, then no power.
        exact = 20+3*(1-math.exp(-.23/2))*math.exp(-.77/2)
        errors = []
        for dt in (.1, .025, .00625):
            solved = evolve(csr_matrix((1, 1)), [2], {'U1': [3]}, [1], [1], [0],
                            20, [0], [0], {}, {'duration_s': 1, 'timestep_s': dt,
                            'power_schedules': {'U1': [[0, 1], [.23, 0]]},
                            'schedule_interpolation': 'step'})
            errors.append(abs(solved['final_temperatures_c'][0]-exact))
            self.assertLess(solved['max_energy_residual_w'], 1e-10)
            self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['energy_balance']), .69, 12)
            ledger = solved['energy_balance']
            self.assertAlmostEqual(sum(row['input_energy_j']-row['boundary_energy_j'] for row in ledger),
                                   2*(solved['final_temperatures_c'][0]-20), 11)
        self.assertLess(errors[2], errors[1])
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[2], 5e-4)

    def test_vacuum_radiation_refines_to_independent_nonlinear_ode(self):
        from scipy.integrate import solve_ivp
        sigma = 5.670374419e-8
        reference = solve_ivp(lambda _, t: [5-.01*.9*sigma*((t[0]+273.15)**4-293.15**4)],
                              (0, 10), [20.], method='DOP853', rtol=1e-11, atol=1e-12)
        self.assertTrue(reference.success)
        errors = []
        boundary, _ = boundary_settings('vacuum', {'board_emissivity': .9})
        self.assertEqual(boundary['board_h_w_m2k'], 0)
        for dt in (.5, .1, .025):
            solved = evolve(csr_matrix((1, 1)), [1], {'U1': [5]}, [.01],
                            [boundary['board_h_w_m2k']], [boundary['board_emissivity']],
                            20, [0], [0], {}, {'duration_s': 10, 'timestep_s': dt})
            errors.append(abs(solved['final_temperatures_c'][0]-reference.y[0, -1]))
            self.assertLess(solved['max_energy_residual_w'], 1e-8)
            self.assertAlmostEqual(sum(row['input_energy_j'] for row in solved['energy_balance']), 50, 11)
            self.assertGreater(sum(row['boundary_energy_j'] for row in solved['energy_balance']), 0)
        self.assertLess(errors[2], errors[1])
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[2], .03)

    def test_exact_schedule_time_does_not_create_roundoff_interval(self):
        solved = self.run_rc(.1, h=0, schedule=[[0, 1], [.3, 0]])
        rows = solved['energy_balance']
        self.assertIn(.3, [row['time_s'] for row in rows])
        self.assertGreater(min(row['elapsed_s'] for row in rows), .099999999)
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in rows), .45, 12)

    def test_invalid_schedules_shapes_and_physical_boundaries_are_rejected(self):
        def run(**overrides):
            values = dict(laplacian=csr_matrix((1, 1)), capacity=[1], source_vectors={'U1': [1]},
                          surface_area=[1], h=[1], emissivity=[0], ambient=20,
                          contact_g=[0], contact_rhs=[0], fixed={},
                          settings={'duration_s': 1, 'timestep_s': .1})
            values.update(overrides)
            return evolve(**values)
        for points in ([], [1], [[0]], [[True, 1]], [[0, False]], [[0, float('nan')]],
                       [[0, 1], [0, 2]], [[-1, 1]], [[0, -1]]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                run(settings={'duration_s': 1, 'timestep_s': .1, 'power_schedules': {'U1': points}})
        for overrides in ({'source_vectors': {'U1': [1, 2]}}, {'capacity': [[1]]},
                          {'h': [-1]}, {'surface_area': [float('nan')]}, {'emissivity': [1.1]},
                          {'fixed': {3: 20}}, {'fixed': {0: -300}}, {'ambient': float('nan')},
                          {'source_vectors': {'U1': [-1]}}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                run(**overrides)
        for extra in ({'duration_s': True}, {'timestep_s': float('inf')},
                      {'schedule_interpolation': 'spline'}, {'frame_stride': True},
                      {'power_schedules': {'unknown': [[0, 1]]}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                run(settings={'duration_s': 1, 'timestep_s': .1, **extra})

    def test_air_vacuum_environment_validation_has_no_boolean_or_nonfinite_coefficients(self):
        for environment in ('air', 'vacuum'):
            for extra in ({'board_h_w_m2k': float('nan')}, {'board_airflow_m_s': True},
                          {'board_emissivity': 1.1}, {'sink_emissivity': {'U1': -1}},
                          {'sink_h_w_m2k': -1}):
                with self.subTest(environment=environment, extra=extra), self.assertRaises(ValueError):
                    boundary_settings(environment, extra)
        with self.assertRaises(ValueError):
            boundary_settings('vacuum', {'sink_airflow_m_s': .01})
        with self.assertRaises(ValueError):
            boundary_settings('sealed', {'board_h_w_m2k': 1, 'enclosure_temperature_c': True})

    def test_spatial_board_air_and_vacuum_transients_reject_heat_and_balance(self):
        for environment in ('air', 'vacuum'):
            with self.subTest(environment=environment):
                geometry, view, result, settings = inputs(environment)
                settings.update(board_emissivity=.85, transient_settings={
                    'duration_s': 2, 'timestep_s': .5,
                    'copper_volumetric_capacity_j_m3k': 3.45e6,
                    'dielectric_volumetric_capacity_j_m3k': 1.8e6})
                solved = solve_multilayer_thermal(geometry, view, result, settings)
                transient = solved['transient']
                self.assertLess(transient['max_energy_residual_w'], 1e-8)
                self.assertGreater(max(transient['final_temperatures_c']), 20)
                self.assertGreater(sum(row['boundary_energy_j'] for row in transient['energy_balance']), 0)
                self.assertAlmostEqual(sum(row['input_energy_j'] for row in transient['energy_balance']), 2, 11)
                if environment == 'vacuum':
                    self.assertEqual(solved['heat_balance']['convection_w'], 0)
