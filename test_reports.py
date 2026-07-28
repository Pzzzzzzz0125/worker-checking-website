import unittest
from datetime import date, timedelta
from unittest.mock import patch

from api._reports import california_overtime, pay_period
from api.reports import handler as ReportRouter
from report_handlers.location_detail import handler as LocationDetailHandler


class ReportTests(unittest.TestCase):
    def test_location_detail_uses_payroll_access_gate(self):
        request = object.__new__(ReportRouter)
        with (
            patch.object(ReportRouter, "action", return_value="location_detail"),
            patch("api.reports.require_payroll_access", return_value=False) as access,
            patch.object(LocationDetailHandler, "do_GET") as location_handler,
        ):
            ReportRouter.do_GET(request)
        access.assert_called_once_with(request)
        location_handler.assert_not_called()

    def test_pay_period_uses_actual_month_end(self):
        self.assertEqual(pay_period("2026-02", "2"), (date(2026, 2, 16), date(2026, 2, 28)))

    def test_w2_weekly_overtime_looks_across_pay_period_boundary(self):
        monday = date(2026, 6, 29)
        days = [
            {
                "worker_key": "1",
                "date": (monday + timedelta(days=offset)).isoformat(),
                "status": "worked",
                "total_hours": 8,
            }
            for offset in range(6)
        ]
        result = california_overtime(days, "1", date(2026, 7, 1), date(2026, 7, 15), "W2")
        self.assertEqual(result["2026-07-04"]["overtime_hours"], 8)
        contractor = california_overtime(days, "1", date(2026, 7, 1), date(2026, 7, 15), "1099")
        self.assertEqual(contractor["2026-07-04"]["overtime_hours"], 0)
        self.assertEqual(contractor["2026-07-04"]["regular_hours"], 8)


if __name__ == "__main__":
    unittest.main()
