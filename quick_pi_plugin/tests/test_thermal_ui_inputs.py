import unittest

from quick_pi_plugin.ui import _parse_sink_areas


class SinkAreaInputTests(unittest.TestCase):
    def test_one_or_multiple_explicit_areas(self):
        self.assertEqual(_parse_sink_areas('1200',['U1']),{'U1':1200.})
        self.assertEqual(_parse_sink_areas('U1=1200, U2=800',['U1','U2']),
                         {'U1':1200.,'U2':800.})

    def test_missing_duplicate_unknown_and_invalid_rejected(self):
        for raw in ('U1=1200','U1=1200, U1=800, U2=700',
                    'U1=1200, U3=700','U1=-1, U2=700','U1=nan, U2=700'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                _parse_sink_areas(raw,['U1','U2'])


if __name__=='__main__':unittest.main()
