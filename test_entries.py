import unittest

from report_handlers.entries import joined_days, save_rows


def record(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class FakeBase:
    def __init__(self):
        self.saved = {}
        self.deleted = []

    def records(self, table_name, **kwargs):
        del kwargs
        if table_name == "Location Entries":
            return [
                record(
                    "old-location",
                    **{
                        "Location Entry Key": "7|2026-07-01|1",
                        "Work Day Key": "7|2026-07-01",
                    },
                )
            ]
        return []

    def batch_set_by_key(self, table_name, key_field, rows, **kwargs):
        del key_field, kwargs
        self.saved[table_name] = rows
        return {"created": len(rows), "updated": 0}

    def delete_record_ids(self, table_name, record_ids):
        self.deleted.extend((table_name, value) for value in record_ids)
        return len(record_ids)


class EntryTests(unittest.TestCase):
    def test_multiple_cost_centers_preserve_location_total_after_rounding(self):
        base = FakeBase()
        result = save_rows(
            base,
            [
                {
                    "worker_id": 7,
                    "date": "2026-07-01",
                    "status": "worked",
                    "total_hours": 8,
                    "locations": [
                        {
                            "name": "444 Pocatello",
                            "hours": None,
                            "cost_centers": [
                                {"id": "A", "name": "One"},
                                {"id": "B", "name": "Two"},
                                {"id": "C", "name": "Three"},
                            ],
                        }
                    ],
                }
            ],
            {"7": {"id": 7, "key": "7", "name": "Ana", "active": True}},
        )
        locations = base.saved["Location Entries"]
        self.assertEqual(sum(item["Regular Hours"] for item in locations), 8)
        self.assertEqual([item["Regular Hours"] for item in locations], [2.67, 2.67, 2.66])
        self.assertEqual(result["days"], 1)
        self.assertEqual(base.deleted, [("Location Entries", "old-location")])

    def test_joined_days_recombines_cost_center_rows(self):
        day = record(
            "day",
            **{
                "Work Day Key": "7|2026-07-01",
                "Worker Key": "7",
                "Work Date": "2026-07-01",
                "Status": "worked",
                "Total Hours": 8,
            },
        )
        locations = [
            record(
                "a",
                **{
                    "Work Day Key": "7|2026-07-01",
                    "Location": "444",
                    "Regular Hours": 4,
                    "Cost Center ID": "A",
                    "Cost Center Name": "One",
                },
            ),
            record(
                "b",
                **{
                    "Work Day Key": "7|2026-07-01",
                    "Location": "444",
                    "Regular Hours": 4,
                    "Cost Center ID": "B",
                    "Cost Center Name": "Two",
                },
            ),
        ]
        output = joined_days([day], locations)["7|2026-07-01"]
        self.assertEqual(output["locations"][0]["hours"], 8)
        self.assertEqual(len(output["locations"][0]["cost_centers"]), 2)


if __name__ == "__main__":
    unittest.main()
