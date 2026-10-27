"""Review rules must preserve captures and prevent partial or ambiguous edits."""
from types import SimpleNamespace
import unittest

from bulk_label_editor_plugin.rules import compile_rule, validate_changes, apply_reviewed
from bulk_label_editor_plugin.cli import main


def field(value, kind="PCB text"):
    item = SimpleNamespace(current=value, kind=kind, value=value)
    item.getter = lambda: item.value
    item.setter = lambda new: setattr(item, "value", new)
    return item


class RuleTests(unittest.TestCase):
    def test_wildcards_preserve_bus_brackets_and_capture_content(self):
        self.assertEqual(compile_rule("CH?_BUS[*]", "LAN?_DATA[*]")("CH2_BUS[10]"), "LAN2_DATA[10]")
        self.assertEqual(compile_rule("CH*_MAIN", "PORT*_A")("ch12_main"), "PORT12_A")
        self.assertEqual(compile_rule("DATA[0]", "D0")("DATA0"), "DATA0")
        self.assertEqual(compile_rule("A*", "*_*_*")("A*?x"), "*?x_*_*")

    def test_regex_and_invalid_rules(self):
        self.assertEqual(compile_rule(r"^R(\d+)$", r"X\1", regex=True)("R12"), "X12")
        self.assertEqual(compile_rule("R*", "X*", case_sensitive=True)("r2"), "r2")
        with self.assertRaises(ValueError):
            compile_rule("", "anything")
        with self.assertRaises(Exception):
            compile_rule("(x)", r"\9", regex=True)
        with self.assertRaisesRegex(ValueError, "Invalid regex replacement"):
            compile_rule("(?P<foo>a)", r"\g<missing>", regex=True)

    def test_duplicate_refs_and_blank_replacements_rejected(self):
        first, second = field("R1", "Reference"), field("R2", "Reference")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_changes([first, second], [(first, "R1", "r2")])
        with self.assertRaisesRegex(ValueError, "nonempty"):
            validate_changes([first], [(first, "R1", "")])
        validate_changes([first, second], [(first, "R1", "R2"), (second, "R2", "R1")])

    def test_stale_batch_does_not_write_any_field(self):
        first, second = field("A"), field("B")
        second.value = "external change"
        with self.assertRaisesRegex(ValueError, "since review"):
            apply_reviewed([(first, "A", "X"), (second, "B", "Y")])
        self.assertEqual(first.value, "A")

    def test_mutating_failure_rolls_back_entire_batch(self):
        first, second = field("A"), field("B")
        def fail(new):
            second.value = new
            if new == "Y":
                raise RuntimeError("rejected")
        second.setter = fail
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            apply_reviewed([(first, "A", "X"), (second, "B", "Y")])
        self.assertEqual((first.value, second.value), ("A", "B"))

    def test_unacknowledged_write_and_undo_redo(self):
        first = field("A")
        first.setter = lambda _new: None
        with self.assertRaisesRegex(RuntimeError, "confirm"):
            apply_reviewed([(first, "A", "B")])
        first.setter = lambda new: setattr(first, "value", new)
        change = [(first, "A", "B")]
        apply_reviewed(change)
        apply_reviewed(change, reverse=True)
        self.assertEqual(first.value, "A")
        apply_reviewed(change)
        self.assertEqual(first.value, "B")

    def test_fresh_editor_readback_can_reject_local_proto_success(self):
        first = field("A")
        remote = {"text": "A"}
        def setter(value):
            first.value = value  # IPC's local proto reports success.
            remote["text"] = "normalized" if value == "B" else value
        first.setter = setter
        checks = []
        def verify(expected):
            checks.append(remote["text"])
            if remote["text"] != expected[0][1]:
                raise RuntimeError("fresh readback differs")
        with self.assertRaisesRegex(RuntimeError, "fresh readback"):
            apply_reviewed([(first, "A", "B")], verify=verify)
        self.assertEqual(checks, ["normalized", "A"])
        self.assertEqual((first.value, remote["text"]), ("A", "A"))

    def test_cli_data_preview_needs_no_board(self):
        import contextlib, io, json
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(main(["preview", "A1", "B2", "--find", "A*", "--replace", "X*"]), 0)
        self.assertEqual(json.loads(stream.getvalue())["changes"], [{"current": "A1", "new": "X1"}])


if __name__ == "__main__":
    unittest.main()
