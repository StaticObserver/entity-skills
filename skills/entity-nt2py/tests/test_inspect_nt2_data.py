"""Unit tests for the pure helpers in scripts/inspect_nt2_data.py.

The module only imports nt2/numpy inside functions, so these tests load the
script file directly with importlib and never require nt2 to be installed.
"""

import importlib.util
import math
import os
import unittest
from pathlib import Path

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "inspect_nt2_data.py",
)

spec = importlib.util.spec_from_file_location("inspect_nt2_data", SCRIPT)
inspect_nt2_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspect_nt2_data)

try:
    import numpy as np
except ImportError:
    np = None


class IsWithinTest(unittest.TestCase):
    def test_path_inside_parent(self):
        self.assertTrue(inspect_nt2_data._is_within(
            Path("/data/run/output.json"), Path("/data/run")))

    def test_path_equal_to_parent(self):
        self.assertTrue(inspect_nt2_data._is_within(
            Path("/data/run"), Path("/data/run")))

    def test_path_outside_parent(self):
        self.assertFalse(inspect_nt2_data._is_within(
            Path("/elsewhere/output.json"), Path("/data/run")))

    def test_sibling_with_common_prefix_is_not_within(self):
        # "/data/run2" must not count as inside "/data/run".
        self.assertFalse(inspect_nt2_data._is_within(
            Path("/data/run2/output.json"), Path("/data/run")))

    def test_parent_escape_is_not_within(self):
        self.assertFalse(inspect_nt2_data._is_within(
            Path("/data/output.json"), Path("/data/run")))

    def test_output_inside_data_root_is_refused(self):
        # Mirrors the safety guard in main(): a nested output path is
        # detected as within the data root and therefore unsafe.
        data_root = Path("/sim/output")
        output = data_root / "probe.json"
        self.assertTrue(inspect_nt2_data._is_within(output, data_root))
        safe_output = Path("/tmp/probe.json")
        self.assertFalse(inspect_nt2_data._is_within(safe_output, data_root))


class JsonScalarTest(unittest.TestCase):
    def test_nan_becomes_none(self):
        self.assertIsNone(inspect_nt2_data._json_scalar(float("nan")))

    def test_positive_inf_becomes_none(self):
        self.assertIsNone(inspect_nt2_data._json_scalar(float("inf")))

    def test_negative_inf_becomes_none(self):
        self.assertIsNone(inspect_nt2_data._json_scalar(float("-inf")))

    def test_finite_float_passes_through(self):
        self.assertEqual(inspect_nt2_data._json_scalar(1.5), 1.5)

    def test_plain_scalars_pass_through(self):
        self.assertEqual(inspect_nt2_data._json_scalar(3), 3)
        self.assertEqual(inspect_nt2_data._json_scalar("abc"), "abc")
        self.assertIs(inspect_nt2_data._json_scalar(True), True)
        self.assertIsNone(inspect_nt2_data._json_scalar(None))

    def test_bytes_decode_with_replacement(self):
        self.assertEqual(inspect_nt2_data._json_scalar(b"hello"), "hello")
        self.assertEqual(
            inspect_nt2_data._json_scalar(b"bad\xffutf8"), "bad�utf8")

    def test_unknown_object_falls_back_to_str(self):
        self.assertEqual(inspect_nt2_data._json_scalar(Path("/x/y")), "/x/y")

    @unittest.skipIf(np is None, "numpy not installed")
    def test_numpy_scalars_are_unwrapped(self):
        self.assertEqual(inspect_nt2_data._json_scalar(np.int64(7)), 7)
        self.assertIsNone(inspect_nt2_data._json_scalar(np.float64("nan")))
        self.assertIsNone(inspect_nt2_data._json_scalar(np.float64("inf")))
        self.assertEqual(inspect_nt2_data._json_scalar(np.float64(2.5)), 2.5)
        self.assertFalse(math.isnan(inspect_nt2_data._json_scalar(np.float64(2.5))))


class UniqueTest(unittest.TestCase):
    def test_deduplicates_preserving_order(self):
        self.assertEqual(
            inspect_nt2_data._unique(["a", "b", "a", "c", "b"]),
            ["a", "b", "c"])

    def test_empty_input(self):
        self.assertEqual(inspect_nt2_data._unique([]), [])

    def test_all_duplicates(self):
        self.assertEqual(inspect_nt2_data._unique(["x", "x", "x"]), ["x"])


if __name__ == "__main__":
    unittest.main()
