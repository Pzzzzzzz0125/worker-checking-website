import unittest

from report_handlers.workers import list_workers, update_worker


def record(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class FakeBase:
    def __init__(self):
        self.saved = None
        self.rows = [
            record(
                "worker-7",
                **{
                    "Worker Key": "7",
                    "Name": "Chris Cong",
                    "Normalized Name": "chris cong",
                    "Worker Type": "1099",
                    "Active": True,
                    "Daily Rate": 300,
                    "Display Order": 2,
                    "Aliases": "Chris",
                    "Notes": "Check only",
                },
            ),
            record(
                "worker-2",
                **{
                    "Worker Key": "2",
                    "Name": "Cesar Ramos",
                    "Normalized Name": "cesar ramos",
                    "Worker Type": "W2",
                    "Active": False,
                    "Daily Rate": 270,
                    "Display Order": 1,
                    "Aliases": "",
                    "Notes": "",
                },
            ),
        ]

    def records(self, table_name, **kwargs):
        self.assert_table = table_name
        self.cache_seconds = kwargs.get("cache_seconds")
        return self.rows

    def set_by_key(self, table_name, key_field, key, fields):
        self.saved = (table_name, key_field, key, fields)
        return {"created": False, "record_id": "worker-7"}


class WorkerProfileTests(unittest.TestCase):
    def test_list_workers_returns_full_master_profiles(self):
        base = FakeBase()
        workers = list_workers(base)
        self.assertEqual(base.assert_table, "Workers")
        self.assertEqual(base.cache_seconds, 0)
        self.assertEqual(workers[0]["name"], "Chris Cong")
        self.assertEqual(workers[0]["daily_rate"], 300)
        self.assertEqual(workers[1]["worker_type"], "W2")

    def test_update_worker_validates_and_saves_supported_fields(self):
        base = FakeBase()
        updated = update_worker(
            base,
            {
                "worker_key": "7",
                "name": "Christopher Cong",
                "worker_type": "W-2",
                "active": False,
                "daily_rate": 325.5,
                "display_order": 4,
                "aliases": "Chris; Christopher",
                "notes": "Direct deposit",
            },
        )
        self.assertEqual(updated["worker_type"], "W2")
        self.assertEqual(updated["daily_rate"], 325.5)
        self.assertEqual(base.saved[0:3], ("Workers", "Worker Key", "7"))
        self.assertEqual(base.saved[3]["Normalized Name"], "christopher cong")
        self.assertFalse(base.saved[3]["Active"])

    def test_update_worker_rejects_unknown_classification(self):
        with self.assertRaisesRegex(ValueError, "W-2 or 1099"):
            update_worker(
                FakeBase(),
                {
                    "worker_key": "7",
                    "name": "Chris Cong",
                    "worker_type": "employee",
                    "active": True,
                    "daily_rate": 300,
                    "display_order": 2,
                },
            )


if __name__ == "__main__":
    unittest.main()
