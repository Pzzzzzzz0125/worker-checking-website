import unittest

from worklog_parser import format_work_cell, parse_work_cell


class NormalizedWorkCellTests(unittest.TestCase):
    def assert_round_trip(self, value, status, total, locations, extra=0):
        parsed = parse_work_cell(value).to_dict()
        self.assertEqual(parsed["status"], status)
        self.assertEqual(parsed["total_hours"], total)
        self.assertEqual(parsed["locations"], locations)
        self.assertEqual(parsed["extra_pay"], extra)
        if status == "worked":
            self.assertEqual(
                format_work_cell(status, total, locations, extra), value
            )

    def test_normalized_examples(self):
        examples = [
            ("444", "worked", 8.0, [{"name": "444", "hours": None}], 0),
            ("444;111", "worked", 8.0, [
                {"name": "444", "hours": None},
                {"name": "111", "hours": None},
            ], 0),
            ("432(3);1151(5)", "worked", 8.0, [
                {"name": "432", "hours": 3.0},
                {"name": "1151", "hours": 5.0},
            ], 0),
            ("528 Downing(6)", "worked", 6.0, [
                {"name": "528 Downing", "hours": 6.0},
            ], 0),
            ("444(4)", "worked", 4.0, [{"name": "444", "hours": 4.0}], 0),
            ("669, ot 2h", "worked", 10.0, [{"name": "669", "hours": None}], 0),
            ("444;111, ot 2h", "worked", 10.0, [
                {"name": "444", "hours": None},
                {"name": "111", "hours": None},
            ], 0),
            ("432(3);1151(5), ot 2h", "worked", 10.0, [
                {"name": "432", "hours": 3.0},
                {"name": "1151", "hours": 5.0},
            ], 0),
            ("1545, ex $20", "worked", 8.0, [{"name": "1545", "hours": None}], 20.0),
            ("1545, ot 2h, ex $20", "worked", 10.0, [{"name": "1545", "hours": None}], 20.0),
        ]
        for example in examples:
            with self.subTest(value=example[0]):
                self.assert_round_trip(*example)

    def test_off_variants(self):
        self.assertEqual(parse_work_cell("off").status, "off")
        self.assertEqual(parse_work_cell("off (vacation)").status, "off")
        self.assertEqual(parse_work_cell("-").status, "unknown")

    def test_legacy_input_exports_as_normalized(self):
        parsed = parse_work_cell("432 (3h) / 1151 (5h), OT 2 hours").to_dict()
        self.assertEqual(
            format_work_cell(
                parsed["status"], parsed["total_hours"],
                parsed["locations"], parsed["extra_pay"]
            ),
            "432(3);1151(5), ot 2h",
        )


if __name__ == "__main__":
    unittest.main()
