import unittest
from pathlib import Path

from api._migration_preview import _location_hours, _worker_registry, build_preview
from worklog_parser import parse_work_cell


ROOT = Path(__file__).parent


class MigrationPreviewTests(unittest.TestCase):
    def test_worker_registry_merges_close_spelling_but_keeps_duplicate_rows(self):
        workbook = {
            "sheets": [
                {
                    "workers": [
                        {"name": "Roberto Rojas"},
                        {"name": "Chris Lee"},
                        {"name": "Chris Lee"},
                    ]
                },
                {
                    "workers": [
                        {"name": "Robert Rojas"},
                        {"name": "Chris Lee"},
                        {"name": "Chris Lee"},
                    ]
                },
            ]
        }
        workers, aliases = _worker_registry(workbook)
        self.assertEqual(len(workers), 3)
        self.assertEqual(aliases["roberto rojas"], aliases["robert rojas"])
        self.assertNotEqual(aliases["chris lee"], aliases["chris lee#2"])

    def test_location_hours_preserve_regular_and_overtime_totals(self):
        parsed = parse_work_cell("432(3);1151(5), ot 2h")
        self.assertEqual(_location_hours(parsed), [(3.0, 0.0), (5.0, 2.0)])
        equal = parse_work_cell("444;111, ot 2h")
        self.assertEqual(_location_hours(equal), [(5.0, 0.0), (3.0, 2.0)])

    @unittest.skipUnless(
        (ROOT / "Speed Payroll.xlsx").exists(),
        "Payroll reference workbook is not checked into the repository.",
    )
    def test_authoritative_workbooks_have_expected_shape(self):
        result = build_preview(
            (ROOT / "2026 Worker's information - location standardized.xlsx").read_bytes(),
            (ROOT / "Cost Code and Cost Type Keep the Most Updated.xlsx").read_bytes(),
            (ROOT / "Speed Payroll.xlsx").read_bytes(),
        )
        self.assertEqual(result["mode"], "preview_only")
        self.assertEqual(result["counts"]["workers"], 53)
        self.assertEqual(result["counts"]["active_workers"], 37)
        self.assertEqual(result["counts"]["work_days"], 6872)
        self.assertEqual(result["counts"]["cost_centers"], 464)


if __name__ == "__main__":
    unittest.main()
