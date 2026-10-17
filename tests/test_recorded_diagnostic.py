"""Real saved diagnostic inputs: regression evidence, never performance proof."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from evidence import read
from reproduce_matchups import reproduce


class RecordedDiagnosticTests(unittest.TestCase):
    def test_saved_805_failures_reproduce_and_full_population_resolves_all(self):
        path = ROOT / "data/verification/2026/w06/dcf4bce0b2d3a162bdea39217eb6ae0ee2545e3895cce129338afc715a5e8e2a.json.gz"
        payload = read(path)
        subset, full = reproduce(payload, True), reproduce(payload)
        self.assertEqual((subset["population"], subset["checked"], subset["failure_count"]), (445, 1864, 805))
        self.assertEqual((full["population"], full["checked"], full["failure_count"]), (840, 1864, 0))
        self.assertEqual(full["input_provenance"], "CONTEMPORANEOUS_REFETCH_NOT_ORIGINAL_BUILDER_PROOF")


if __name__ == "__main__":
    unittest.main()
