import unittest
from types import SimpleNamespace
from wayricad_runtime.fields import apply_fields


class ReviewedFieldsTests(unittest.TestCase):
    def item(self, value):
        state = [value]
        return state, SimpleNamespace(getter=lambda: state[0], setter=lambda text: state.__setitem__(0, text))

    def test_apply_undo_redo_use_reviewed_values(self):
        state, item = self.item("A")
        changes = [(item, "A", "B")]
        apply_fields(changes)
        self.assertEqual(state, ["B"])
        apply_fields(changes, reverse=True)
        self.assertEqual(state, ["A"])
        apply_fields(changes)
        self.assertEqual(state, ["B"])

    def test_stale_preview_rejects_all_writes(self):
        one, a = self.item("A")
        _, b = self.item("changed")
        with self.assertRaises(ValueError):
            apply_fields([(a, "A", "B"), (b, "C", "D")])
        self.assertEqual(one, ["A"])

    def test_partial_failure_restores_prior_changes(self):
        one, a = self.item("A")
        two, b = self.item("C")
        def fail_on_new(value):
            two[0] = value
            if value == "D":
                raise RuntimeError("write failed")
        b.setter = fail_on_new
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            apply_fields([(a, "A", "B"), (b, "C", "D")])
        self.assertEqual((one, two), (["A"], ["C"]))
