import unittest

from report_handlers.schedule import _selected_dates


class ScheduleDateSelectionTests(unittest.TestCase):
    def test_single_day_is_one_date(self):
        self.assertEqual(
            _selected_dates({"schedule_date": "2026-08-10", "schedule_end_date": "2026-08-10"}),
            ["2026-08-10"],
        )

    def test_range_expands_each_day(self):
        self.assertEqual(
            _selected_dates({"schedule_date": "2026-08-10", "schedule_end_date": "2026-08-12"}),
            ["2026-08-10", "2026-08-11", "2026-08-12"],
        )

    def test_calendar_selection_is_sorted_and_deduplicated(self):
        self.assertEqual(
            _selected_dates({"schedule_dates": ["2026-08-12", "2026-08-10", "2026-08-12"]}),
            ["2026-08-10", "2026-08-12"],
        )

    def test_calendar_selection_has_31_date_limit(self):
        with self.assertRaises(ValueError):
            _selected_dates({"schedule_dates": [f"2026-08-{day:02d}" for day in range(1, 33)]})


if __name__ == "__main__":
    unittest.main()
