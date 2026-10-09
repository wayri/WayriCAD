"""Run the offline report's actual JavaScript measurement behavior in Node."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node is needed for report JavaScript checks")
class ReportMeasurementTests(unittest.TestCase):
    def test_report_measurements(self):
        script = Path(__file__).with_name("report_measurements.cjs")
        result = subprocess.run(
            [shutil.which("node"), str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
