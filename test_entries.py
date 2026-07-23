import unittest

from report_handlers.entries import clear_day, joined_days, save_rows


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
    worker_map = {"7": {"id": 7, "key": "7", "name": "Ana", "active": True}}

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
            self.worker_map,
        )
        locations = base.saved["Location Entries"]
        self.assertEqual(sum(item["Regular Hours"] for item in locations), 8)
        self.assertEqual([item["Regular Hours"] for item in locations], [2.67, 2.67, 2.66])
        self.assertEqual(result["days"], 1)
        self.assertEqual(base.deleted, [("Location Entries", "old-location")])

    def test_location_ranges_drive_regular_and_overtime_hours(self):
        base = FakeBase()
        save_rows(
            base,
            [
                {
                    "worker_id": 7,
                    "date": "2026-07-02",
                    "status": "worked",
                    "total_hours": 9,
                    "overtime_hours": 1,
                    "locations": [
                        {"name": "A", "start_time": "08:00", "end_time": "12:00", "cost_centers": [{"id": "1", "name": "One"}]},
                        {"name": "B", "start_time": "12:00", "end_time": "17:00", "cost_centers": [{"id": "2", "name": "Two"}]},
                    ],
                }
            ],
            self.worker_map,
        )
        locations = base.saved["Location Entries"]
        self.assertEqual(sum(item["Regular Hours"] for item in locations), 8)
        self.assertEqual(sum(item["Overtime Hours"] for item in locations), 1)
        self.assertEqual(locations[0]["Start Time"], "08:00")
        self.assertEqual(locations[1]["End Time"], "17:00")

    def test_conflicting_total_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Time conflict"):
            save_rows(
                FakeBase(),
                [
                    {
                        "worker_id": 7,
                        "date": "2026-07-02",
                        "status": "worked",
                        "total_hours": 8,
                        "overtime_hours": 0,
                        "locations": [
                            {"name": "A", "start_time": "08:00", "end_time": "17:00", "cost_centers": [{"id": "1", "name": "One"}]},
                        ],
                    }
                ],
                self.worker_map,
            )

    def test_clear_day_deletes_work_day_and_linked_locations(self):
        class ClearBase(FakeBase):
            def records(self, table_name, **kwargs):
                del kwargs
                if table_name == "Work Days":
                    return [
                        record(
                            "day-record",
                            **{
                                "Work Day Key": "7|2026-07-02",
                                "Worker Key": "7",
                                "Work Date": "2026-07-02",
                            },
                        )
                    ]
                if table_name == "Location Entries":
                    return [
                        record(
                            "location-record",
                            **{
                                "Location Entry Key": "7|2026-07-02|1|1",
                                "Work Day Key": "7|2026-07-02",
                                "Worker Key": "7",
                                "Work Date": "2026-07-02",
                            },
                        )
                    ]
                return []

        base = ClearBase()
        result = clear_day(base, "7", "2026-07-02")
        self.assertEqual(result["deleted_days"], 1)
        self.assertEqual(result["deleted_locations"], 1)
        self.assertEqual(
            base.deleted,
            [
                ("Location Entries", "location-record"),
                ("Work Days", "day-record"),
            ],
        )

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
