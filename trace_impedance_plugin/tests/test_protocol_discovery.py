"""Pure discovery tests; import the owned module without loading wx packages."""

import importlib.util
import json
from pathlib import Path
import unittest


_SPEC = importlib.util.spec_from_file_location(
    "rlc_protocol_discovery", Path(__file__).resolve().parents[1] / "protocol_discovery.py")
discovery = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(discovery)


class ProtocolDiscoveryTests(unittest.TestCase):
    def test_fpga_gt_families_and_polarity_before_lane_number(self):
        for family in ('GTH','GTY','GTX','GTP'):
            for prefix in (family+'_',family):
                names=['/FPGA/'+prefix+'TXP0','/FPGA/'+prefix+'TXN0','/OTHER/'+prefix+'TXN0']
                rows={row['net']:row for row in self.matches(names)}
                self.assertEqual(rows[names[0]]['profile_id'],'fpga-gt')
                self.assertEqual(rows[names[0]]['mate'],names[1])
                self.assertIsNone(rows[names[2]]['mate'])
        self.assertEqual(self.matches(['GTHRESHOLD','GTX_VCC','SCAN','GTY_POWER']),[])

    def matches(self, names, **kwargs):
        return discovery.discover_protocols(names, **kwargs)["matches"]

    def test_catalog_and_serialization(self):
        profiles = discovery.list_profiles()
        by_id = {p["id"]: p for p in profiles}
        for key in ("can", "rs485", "serdes", "ddr", "m2", "hdmi", "displayport"):
            self.assertIsNone(by_id[key]["target_ohm"])
        self.assertTrue(by_id["m2"]["review_required"])
        self.assertTrue(all(isinstance(p["differential"], bool) for p in profiles))
        self.assertFalse(any("rate" in k for p in profiles for k in p))
        profiles[0]["aliases"].clear()
        self.assertTrue(discovery.list_profiles()[0]["aliases"])
        result = discovery.discover_protocols(["USB2_DP", "USB2_DM"])
        self.assertEqual(result["schema"], "wayricad.rlc-protocol-discovery/v1")
        json.dumps(result, allow_nan=False)

    def test_all_families(self):
        cases = {
            "USB2_DP": "usb2", "USB3_TX0_P": "usb3", "USB4_TX0_P": "usb4",
            "CANH": "can", "RS485A": "rs485", "MDI0_P": "ethernet-mdi",
            "RGMII_TXD0": "rgmii", "SGMII_TX_P": "sgmii", "10GBASE_KR_TX_P": "10gbase-kr",
            "RF_OUT": "rf", "SERDES_RX0_P": "serdes", "LVDS_CLK_P": "lvds",
            "PCIE_TX0_P": "pcie", "SATA_RX_P": "sata", "DDR4_DQ0": "ddr",
            "I2C1_SDA": "i2c", "SPI2_MOSI": "spi", "UART_TX": "uart",
            "I2S_DATA": "i2s-tdm", "TDM_CLK": "i2s-tdm", "SDIO_D0": "sdio",
            "PCI_AD0": "parallel-pci", "GPIO7": "parallel-gpio", "M.2_TX_P": "m2",
            "HDMI_TX0_P": "hdmi", "DisplayPort_TX0_P": "displayport",
        }
        for name, key in cases.items():
            with self.subTest(name=name):
                self.assertEqual([m["profile_id"] for m in self.matches([name])], [key])

    def test_short_names_substrings_and_power_rails(self):
        names = ["SCAN", "SCAN_RX", "CANARY", "TX", "RX", "P", "N", "DP", "DM",
                 "SDA", "SCL", "SPIKE", "USB_VBUS", "USB2_5V", "USB_3V3",
                 "USB_VDD", "USB_POWER", "USB_GND", "USB_V5", "USB3_PWR_EN", "USB3V3", "USB_VBAT"]
        result = discovery.discover_protocols(names)
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["unclassified"], sorted(names))

    def test_scoped_pair_separators_and_lanes(self):
        names = ["/A/usb-3-tx0-p", "/A/USB_3_TX0_N", "/B/USB3_TX0_N",
                 "/A/USB3_TX1_N", "/A/USB2_TX0_N", "/A/USB4_TX0_N"]
        found = {m["net"]: m for m in self.matches(names)}
        self.assertEqual(found[names[0]]["mate"], names[1])
        self.assertEqual(found[names[1]]["mate"], names[0])
        self.assertTrue(all(found[n]["mate"] is None for n in names[2:]))

    def test_polarity_conventions(self):
        for positive, negative in [("USB_D+", "USB_D-"), ("USB2_DP", "USB2_DM"),
                                   ("CANH", "CANL"), ("CAN_H", "CAN_L"),
                                   ("RS485A", "RS485B"), ("RS485_A", "RS485_B"),
                                   ("PCIE_TX0P", "PCIE_TX0N"), ("DDR_DQS0_P", "DDR_DQS0_N")]:
            with self.subTest(positive=positive):
                found = self.matches(["/sheet/" + positive, "/sheet/" + negative])
                self.assertEqual(len(found), 2)
                self.assertEqual(found[0]["mate"], found[1]["net"])
                self.assertEqual(found[1]["mate"], found[0]["net"])

    def test_ambiguous_mates_not_selected(self):
        result = discovery.discover_protocols(["PCIE_TX0_P", "PCIE_TX0_N", "PCIE-TX0-N"])
        self.assertTrue(all(m["mate"] is None and m["review_required"] for m in result["matches"]))
        self.assertTrue(any(a["reason"] == "multiple_mates" for a in result["ambiguities"]))

    def test_typo_and_confidence(self):
        found = self.matches(["ETHERNTE_TX", "SERDEZ_TX_P", "RGMII_TXD0"])
        self.assertEqual([m["profile_id"] for m in found], ["ethernet-mdi", "rgmii", "serdes"])
        fuzzy = next(m for m in found if m["profile_id"] == "serdes")
        self.assertEqual(fuzzy["method"], "fuzzy")
        self.assertTrue(fuzzy["review_required"])
        self.assertEqual(self.matches(["SERDEZ_TX_P"], min_confidence=0.8), [])
        self.assertEqual(self.matches(["USV_RX", "CNA_H", "SP1_TX", "RXX", "TXP"]), [])

    def test_multiple_protocols_and_m2(self):
        result = discovery.discover_protocols(["USB2_USB3_TX_P", "M2_TX_P"])
        self.assertEqual(len(result["ambiguities"]), 1)
        self.assertEqual(result["ambiguities"][0]["candidates"], ["usb2", "usb3"])
        m2 = next(m for m in result["matches"] if m["profile_id"] == "m2")
        self.assertTrue(m2["review_required"])
        self.assertNotIn("pcie", [m["profile_id"] for m in result["matches"]])

    def test_unspecified_usb_keeps_generation_ambiguity(self):
        result = discovery.discover_protocols(["USB_TX_P"])
        self.assertEqual([m["profile_id"] for m in result["matches"]], ["usb2", "usb3", "usb4"])
        self.assertTrue(all(m["review_required"] for m in result["matches"]))
        self.assertEqual([m["profile_id"] for m in self.matches(["USB_SSTX_P"])], ["usb3"])

    def test_custom_rules_and_evidence(self):
        rules = [dict(pattern="/io/*", kind="wildcard", profile_id="lvds"),
                 dict(pattern=r"^/IO/TX[0-9]_P$", kind="regex", profile_id="pcie")]
        result = discovery.discover_protocols(["/io/tx0_p"], rules)
        self.assertEqual({m["method"] for m in result["matches"]}, {"wildcard", "regex"})
        self.assertTrue(all(m["evidence"] and m["review_required"] for m in result["matches"]))
        self.assertEqual(len(result["ambiguities"]), 1)

    def test_rule_validation(self):
        for pattern in ["(a+)+$", "(?=x)", r"(a)\1", "a*a*a*", "[", "a{1,999}", "a|aa", "x" * 129]:
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                discovery.discover_protocols([], [dict(pattern=pattern, kind="regex", profile_id="rf")])
        for rule in [dict(pattern="*", kind="regex", profile_id="unknown"),
                     dict(pattern="x", kind="other", profile_id="rf"),
                     dict(pattern="[", kind="wildcard", profile_id="rf"), None]:
            with self.assertRaises(ValueError):
                discovery.discover_protocols([], [rule])
        with self.assertRaises(ValueError):
            discovery.discover_protocols([], [dict(pattern="*", kind="wildcard", profile_id="rf")] * 33)

    def test_bounds_and_determinism(self):
        for names in ["USB", [None], [""], ["x" * 257], ["a\nb"], None]:
            with self.assertRaises(ValueError):
                discovery.discover_protocols(names)
        for threshold in [-1, 2, float("nan"), float("inf"), True, "0.8"]:
            with self.assertRaises(ValueError):
                discovery.discover_protocols([], min_confidence=threshold)
        with self.assertRaises(ValueError):
            discovery.discover_protocols("RF_%d" % i for i in range(10001))
        names = ["PCIE_TX0_N", "SPI_MOSI", "PCIE_TX0_P"]
        self.assertEqual(discovery.discover_protocols(names), discovery.discover_protocols(reversed(names)))
        self.assertEqual(discovery.discover_protocols(names), discovery.discover_protocols(names + names))


if __name__ == "__main__":
    unittest.main()
