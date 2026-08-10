from __future__ import annotations

from pathlib import Path
import sys
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
SCRIPTS = SERVICE_ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_retrieval_calibration  # noqa: E402


class RetrievalCalibrationTests(unittest.TestCase):
    def test_fixture_is_machine_comparable_and_all_cases_pass(self) -> None:
        cases = run_retrieval_calibration.load_cases()
        self.assertGreaterEqual(len(cases), 24)
        self.assertLessEqual(len(cases), 40)
        summary = run_retrieval_calibration.run_cases(cases)
        self.assertEqual(len(cases), summary["passed"])
        self.assertEqual(0, summary["failed"], summary["results"])


if __name__ == "__main__":
    unittest.main()
