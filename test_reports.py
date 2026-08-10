import unittest
from datetime import date, timedelta
from unittest.mock import patch

from api._reports import california_overtime, load_report_data, pay_period, report_period
from api.reports import handler as ReportRouter
from report_handlers.location_detail import (
    build_worker_site_detail,
    handler as LocationDetailHandler,
)
from report_handlers.payroll_worker_detail import aggregate_with_estimated_cost
from report_handlers.sites import SiteResolver


class ReportTests(unittest.TestCase):
    def test_report_data_merges_legacy_site_labels_into_formal_address(self):
        class FakeBase:
            def records(self, table_name, **kwargs):
                del kwargs
                if table_name == "Workers":
                    return [{"fields": {
                        "Worker Key": "1", "Name": "Worker A", "Active": True,
                    }}]
                if table_name == "Work Days":
                    return [{"fields": {
                        "Work Day Key": "1|2026-07-01", "Worker Key": "1",
                        "Work Date": "2026-07-01", "Status": "worked", "Total Hours": 8,
                    }}]
                if table_name == "Location Entries":
                    return [
                        {"fields": {
                            "Location Entry Key": "a", "Work Day Key": "1|2026-07-01",
                            "Location": "1073 Crosswind =", "Location Hours": 4,
                        }},
                        {"fields": {
                            "Location Entry Key": "b", "Work Day Key": "1|2026-07-01",
                            "Location": "1073", "Location Hours": 4,
                        }},
                    ]
                return []

        resolver = SiteResolver([{
            "site_key": "crosswind", "name": "1073 Crosswind Ct, San Jose, CA 95120",
            "full_address": "1073 Crosswind Ct, San Jose, CA 95120",
            "address_line_1": "1073 Crosswind Ct", "aliases": "", "active": True,
            "verified": True,
        }])
        with patch("api._reports.load_site_resolver", return_value=resolver):
            result = load_report_data(
                FakeBase(), date(2026, 7, 1), date(2026, 7, 1),
            )
        names = [item["name"] for item in result["days"][0]["locations"]]
        self.assertEqual(names, [
            "1073 Crosswind Ct, San Jose, CA 95120",
            "1073 Crosswind Ct, San Jose, CA 95120",
        ])
        self.assertEqual(result["days"][0]["locations"][0]["raw_name"], "1073 Crosswind =")

    def test_archived_workers_are_excluded_from_report_data(self):
        class FakeBase:
            def records(self, table_name, **kwargs):
                del kwargs
                if table_name == "Workers":
                    return [
                        {"fields": {"Worker Key": "1", "Name": "Active", "Active": True}},
                        {"fields": {"Worker Key": "2", "Name": "Archived", "Active": False}},
                    ]
                if table_name == "Work Days":
                    return [
                        {"fields": {"Work Day Key": "1|2026-07-01", "Worker Key": "1", "Work Date": "2026-07-01", "Status": "worked", "Total Hours": 8}},
                        {"fields": {"Work Day Key": "2|2026-07-01", "Worker Key": "2", "Work Date": "2026-07-01", "Status": "worked", "Total Hours": 8}},
                    ]
                return []

        result = load_report_data(
            FakeBase(), date(2026, 7, 1), date(2026, 7, 15),
        )
        self.assertEqual(set(result["workers"]), {"1"})
        self.assertEqual([day["worker_key"] for day in result["days"]], ["1"])

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

    def test_flexible_report_period_accepts_custom_dates_and_month_default(self):
        self.assertEqual(
            report_period(
                {"from": ["2026-06-29"], "to": ["2026-07-12"]},
                date(2026, 7, 28),
            ),
            (date(2026, 6, 29), date(2026, 7, 12)),
        )
        self.assertEqual(
            report_period({}, date(2026, 7, 28)),
            (date(2026, 7, 1), date(2026, 7, 28)),
        )

    def test_payroll_checks_are_keyed_by_custom_range_end(self):
        class FakeBase:
            def records(self, table_name, **kwargs):
                del kwargs
                if table_name == "Workers":
                    return [{"fields": {
                        "Worker Key": "1", "Name": "Active", "Active": True,
                    }}]
                if table_name == "Payroll Checks":
                    return [{"fields": {
                        "Worker Key": "1",
                        "Period Start": "2026-07-01",
                        "Period End": "2026-07-28",
                        "Checked": True,
                    }}]
                return []

        result = load_report_data(
            FakeBase(),
            date(2026, 7, 1),
            date(2026, 7, 31),
            check_period_start=date(2026, 7, 1),
        )
        self.assertTrue(result["checks"][("1", "2026-07-01", "2026-07-28")])
        self.assertNotIn(("1", "2026-07-01", "2026-07-31"), result["checks"])

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

    def test_site_worker_detail_allocates_weighted_hours_to_selected_site(self):
        data = {
            "workers": {
                "1": {
                    "id": 1, "key": "1", "name": "Worker A",
                    "worker_type": "W2", "daily_rate": 320,
                },
            },
            "days": [{
                "worker_key": "1",
                "date": "2026-07-01",
                "status": "worked",
                "total_hours": 10,
                "locations": [
                    {
                        "name": "Site A", "hours": 5,
                        "cost_centers": [{"id": "100", "name": "Framing"}],
                    },
                    {"name": "Site B", "hours": 5, "cost_centers": []},
                ],
            }],
        }
        result = build_worker_site_detail(
            data, "1", "Site A", date(2026, 7, 1), date(2026, 7, 1),
        )
        self.assertEqual(result["totals"]["hours"], 5)
        self.assertEqual(result["totals"]["regular_hours"], 4)
        self.assertEqual(result["totals"]["overtime_hours"], 1)
        self.assertEqual(result["totals"]["weighted_hours"], 5.5)
        self.assertEqual(result["totals"]["estimated_cost"], 220)
        self.assertEqual(result["days"][0]["cost_centers"][0]["id"], "100")

    def test_payroll_detail_allocates_estimated_cost_by_recorded_hours(self):
        rows = aggregate_with_estimated_cost(
            [{
                "date": "2026-07-01",
                "worker_key": "1",
                "total_hours": 10,
                "weighted_hours": 11,
                "locations": [
                    {"name": "Site A", "hours": 5},
                    {"name": "Site B", "hours": 5},
                ],
            }],
            "locations",
            320,
        )
        self.assertEqual(rows[0]["estimated_cost"], 220)
        self.assertEqual(rows[1]["estimated_cost"], 220)

    def test_payroll_detail_lists_missing_codes_and_reconciles_extra_pay(self):
        rows = aggregate_with_estimated_cost(
            [{
                "date": "2026-07-01",
                "worker_key": "1",
                "total_hours": 8,
                "regular_hours": 8,
                "weighted_hours": 8,
                "extra_pay": 20,
                "cost_centers": [
                    {"id": "CC-1", "name": "Framing", "hours": 3},
                ],
            }],
            "cost_centers",
            320,
        )
        missing = next(row for row in rows if row["name"] == "--")
        self.assertEqual(missing["hours"], 5)
        self.assertEqual(missing["estimated_cost"], 220)
        self.assertEqual(sum(row["estimated_cost"] for row in rows), 340)


if __name__ == "__main__":
    unittest.main()
