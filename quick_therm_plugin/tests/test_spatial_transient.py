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
