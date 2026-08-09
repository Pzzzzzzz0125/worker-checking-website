import unittest

from api.bootstrap import build_bootstrap, build_bootstrap_details
from api.summary import build_summary


def record(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class FakeBase:
    def __init__(self):
        self.data = {
            "Workers": [
                record("rec-worker", **{"Worker Key": "7", "Name": "Ana Diaz", "Worker Type": "W2", "Active": True}),
                record("rec-archived", **{"Worker Key": "8", "Name": "Archived Worker", "Active": False}),
            ],
            "Cost Centers": [
                record(
                    "rec-center",
                    **{"Cost Center ID": "CC-12", "Name": "Framing", "Active": True},
                )
            ],
            "Location Entries": [
                record(
                    "rec-location",
                    **{
                        "Location Entry Key": "alloc-1",
                        "Work Day Key": "7|2026-07-01",
                        "Worker Key": "7",
                        "Work Date": "2026-07-01",
                        "Location": "444 Pocatello",
                        "Cost Center ID": "CC-12",
                        "Cost Center Name": "Framing",
                        "Regular Hours": 8,
                    },
                )
            ],
            "Work Days": [
                record(
                    "rec-day",
                    **{
                        "Work Day Key": "7|2026-07-01",
                        "Worker Key": "7",
                        "Worker Name": "Ana Diaz",
                        "Work Date": "2026-07-01",
                        "Status": "worked",
                        "Total Hours": 10,
                        "Overtime Hours": 2,
                        "Extra Pay": 20,
                        "Start Time": "08:30",
                        "End Time": "18:30",
                        "Confidence": "low",
                    },
                ),
                record(
                    "rec-archived-day",
                    **{
                        "Work Day Key": "8|2026-07-01",
                        "Worker Key": "8",
                        "Worker Name": "Archived Worker",
                        "Work Date": "2026-07-01",
                        "Status": "worked",
                        "Total Hours": 8,
                        "Overtime Hours": 0,
                        "Extra Pay": 0,
                    },
                ),
            ],
        }

    def missing_tables(self):
        return []

    def records(self, name, **kwargs):
        del kwargs
        return self.data.get(name, [])


class LarkBaseReadTests(unittest.TestCase):
    def test_bootstrap_reads_reference_data(self):
        result = build_bootstrap(FakeBase())
        self.assertEqual(result["workers"], [{"id": 7, "worker_key": "7", "name": "Ana Diaz", "active": 1}])
        self.assertEqual(result["cost_centers"], [{"id": "CC-12", "name": "Framing"}])
        self.assertEqual(result["locations"], [])
        details = build_bootstrap_details(FakeBase())
        self.assertEqual(details["locations"], ["444 Pocatello"])
        self.assertEqual(details["last_recorded_date"], "2026-07-01")

    def test_summary_uses_compact_work_day_data(self):
        result = build_summary(FakeBase(), "2026-07-01", "2026-07-15")
        self.assertEqual(result["totals"]["hours"], 10)
        self.assertEqual(result["totals"]["regular_hours"], 8)
        self.assertEqual(result["totals"]["overtime_hours"], 2)
        self.assertEqual(result["totals"]["weighted_hours"], 11)
        self.assertEqual(result["totals"]["extra_pay"], 20)
        self.assertEqual(result["totals"]["active_workers"], 1)
        self.assertEqual(result["totals"]["record_count"], 1)
        self.assertEqual(result["trend_resolution"], "day")
        self.assertEqual(len(result["trend"]), 15)
        self.assertEqual(result["trend"][0], {
            "start": "2026-07-01",
            "label": "Jul 1",
            "regular_hours": 8,
            "weighted_hours": 11,
        })
        self.assertEqual(result["trend"][-1]["weighted_hours"], 0)
        self.assertEqual(result["records"], [])
        self.assertNotIn("daily", result)


if __name__ == "__main__":
    unittest.main()
