"""Behavioral review lifecycle tests for heater/winding generated geometry."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from wayricad_runtime.generated import ReviewedGeometry


class Harness(ReviewedGeometry):
    def __init__(self):
        self.board=object();self.value='1';self.result=object()
        self.fields={'width':SimpleNamespace(GetValue=lambda:self.value)}
        self.preview_items=[]
    def _unattached_items(self):return ['track','via']


class GeneratedReviewTests(unittest.TestCase):
    def test_settings_and_board_changes_require_review(self):
        frame=Harness()
        with patch('wayricad_runtime.generated.board_fingerprint',return_value='a'):
            frame._capture_review();frame._check_review()
            frame.value='2'
            with self.assertRaisesRegex(ValueError,'Settings changed'):frame._check_review()
            frame.value='1'
        with patch('wayricad_runtime.generated.board_fingerprint',return_value='b'):
            with self.assertRaisesRegex(ValueError,'PCB changed'):frame._check_review()

    def test_review_stages_only_unattached_items(self):
        frame=Harness();messages=[]
        frame.status=SimpleNamespace(SetLabel=messages.append)
        frame._report_error=lambda exc:self.fail(str(exc))
        with patch('wayricad_runtime.generated.board_fingerprint',return_value='a'):
            frame._capture_review();frame.show_pcb(None)
        self.assertEqual(frame.preview_items,['track','via'])
        self.assertIn('PCB unchanged',messages[0])
        frame.clear_preview(None)
        self.assertEqual(frame.preview_items,[])
