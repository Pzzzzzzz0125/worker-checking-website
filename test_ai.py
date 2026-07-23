import unittest

from report_handlers.ai import match_worker, normalize_records, resolve_centers


def record(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class FakeBase:
    def records(self, table_name, **kwargs):
        del kwargs
        if table_name == "Workers":
            return [
                record(
                    "worker-1",
                    **{
                        "Worker Key": "1",
                        "Name": "Filimon Acosta",
                        "Normalized Name": "filimon acosta",
                        "Worker Type": "W2",
                        "Active": True,
                        "Daily Rate": 300,
                        "Display Order": 1,
                        "Aliases": "Filimon",
                        "Notes": "",
                    },
                )
            ]
        if table_name == "Cost Centers":
            return [
                record(
                    "center-1",
                    **{
                        "Cost Center ID": "CC-444",
                        "Name": "Framing",
                        "Active": True,
                    },
                )
            ]
        if table_name == "Work Days":
            return [
                record(
                    "day-1",
                    **{
                        "Work Day Key": "1|2026-07-02",
                        "Work Date": "2026-07-02",
                    },
                )
            ]
        if table_name == "Location Entries":
            return []
        raise AssertionError(table_name)


class AIHandlerTests(unittest.TestCase):
    def test_worker_alias_and_cost_center_display_match(self):
        profiles = [
            {
                "id": 1,
                "worker_key": "1",
                "name": "Filimon Acosta",
                "normalized_name": "filimon acosta",
                "aliases": "Filimon",
                "active": True,
            }
        ]
        self.assertEqual(match_worker(profiles, "Filimon")["worker_key"], "1")
        centers = [{"id": "CC-444", "name": "Framing"}]
        self.assertEqual(
            resolve_centers(centers, ["Framing (CC-444)"]),
            centers,
        )

    def test_normalize_records_matches_lark_data_and_existing_day(self):
        result = normalize_records(
            FakeBase(),
            [
                {
                    "worker_name": "Filimon",
                    "date": "2026-07-02",
                    "status": "worked",
                    "locations": ["444 Pocatello"],
                    "regular_hours": 8,
                    "overtime_hours": 0,
                    "total_hours": 8,
                    "extra_pay": 0,
                    "start_time": "",
                    "end_time": "",
                    "cost_centers": ["CC-444"],
                    "notes": "",
                    "confidence": "high",
                    "warning": "",
                    "source_excerpt": "07-02 444 Pocatello",
                }
            ],
            2026,
        )[0]
        self.assertEqual(result["worker_name"], "Filimon Acosta")
        self.assertTrue(result["existing"])
        self.assertTrue(result["ready"])
        self.assertEqual(result["cost_centers"][0]["id"], "CC-444")


if __name__ == "__main__":
    unittest.main()
