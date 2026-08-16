import unittest

from gemini_parser import extraction_prompt
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
                ),
                record(
                    "center-2",
                    **{
                        "Cost Center ID": "CC-555",
                        "Name": "Flooring Labor",
                        "Active": True,
                    },
                ),
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
        if table_name == "Sites":
            return [
                record(
                    "site-1",
                    **{
                        "Site Key": "site-444",
                        "Name": "444 Pocatello Ave",
                        "Full Address": "444 Pocatello Ave, San Jose, CA 95111",
                        "Address Line 1": "444 Pocatello Ave",
                        "Aliases": "444 Pocatello",
                        "Default Cost Code IDs": "CC-444",
                        "Active": True,
                        "Verified": True,
                    },
                ),
                record(
                    "site-2",
                    **{
                        "Site Key": "site-555",
                        "Name": "1933 Everglade Ave",
                        "Full Address": "1933 Everglade Ave, San Jose, CA 95122",
                        "Address Line 1": "1933 Everglade Ave",
                        "Aliases": "1933 Everglade",
                        "Active": True,
                        "Verified": True,
                    },
                ),
            ]
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
                    "cost_centers": ["fram"],
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
        self.assertEqual(result["locations"], ["444 Pocatello Ave"])

    def test_each_site_keeps_its_own_cost_code_assignment(self):
        result = normalize_records(
            FakeBase(),
            [{
                "worker_name": "Filimon",
                "date": "2026-07-02",
                "status": "worked",
                "locations": ["444 Pocatello", "1933 Everglade"],
                "regular_hours": 8,
                "overtime_hours": 0,
                "total_hours": 8,
                "extra_pay": 0,
                "cost_centers": ["framing", "floor"],
                "assignments": [
                    {"site": "444 Pocatello", "cost_codes": ["framing"], "hours": 4, "start_time": "08:30", "end_time": "12:30"},
                    {"site": "1933 Everglade", "cost_codes": ["floor"], "hours": 4, "start_time": "12:30", "end_time": "16:30"},
                ],
                "confidence": "high",
                "warning": "",
                "source_excerpt": "444 framing 4h | 1933 floor 4h",
            }],
            2026,
        )[0]
        self.assertTrue(result["ready"])
        self.assertEqual(result["assignments"][0]["cost_centers"][0]["id"], "CC-444")
        self.assertEqual(result["assignments"][1]["cost_centers"][0]["id"], "CC-555")
        self.assertEqual(result["assignments"][1]["site"], "1933 Everglade Ave")

    def test_prompt_forbids_cross_row_association(self):
        prompt = extraction_prompt("row 1\nrow 2", 2026, ["photo.jpg"])
        self.assertIn("Never carry a Site, work keyword, Cost Code, or hours", prompt)
        self.assertIn("Never copy all of a day's Cost Codes onto all", prompt)
        self.assertIn("photo.jpg", prompt)


if __name__ == "__main__":
    unittest.main()
