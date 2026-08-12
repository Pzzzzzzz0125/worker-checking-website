import os
import unittest
from unittest.mock import patch

from api._lark_sync import (
    latest_events,
    normalize_mirror_fields,
    synchronize_lark,
)


class FakeDatabase:
    def __init__(self, events, mappings=None, work_rows=None):
        self.events = events
        self.mappings = mappings or {}
        self.work_rows = work_rows or ([], [])
        self.completed = []
        self.failed = []
        self.saved_mappings = {}
        self.deleted_mappings = []
        self.settings = {}

    def claim_sync_events(self, _limit):
        return self.events

    def mirror_record_ids(self, _table_name, keys):
        return {key: self.mappings[key] for key in keys if key in self.mappings}

    def work_log_records(self, _keys):
        return self.work_rows

    def get_setting(self, key):
        return self.settings.get(key)

    def set_setting(self, key, value):
        self.settings[key] = value

    def set_mirror_record_ids(self, _table_name, mappings):
        self.saved_mappings.update(mappings)

    def delete_mirror_keys(self, _table_name, keys):
        self.deleted_mappings.extend(keys)

    def complete_sync_events(self, ids):
        self.completed.extend(ids)

    def fail_sync_events(self, ids, error):
        self.failed.append((ids, error))

    def sync_status(self):
        return {
            "enabled": True,
            "pending": len(self.failed),
            "retrying": len(self.failed),
            "synced_last_24h": len(self.completed),
            "last_synced_at": "",
        }


class FakeLark:
    def __init__(self):
        self.updated = []
        self.created = []
        self.deleted = []

    def batch_update_record_ids(self, table_name, rows):
        self.updated.append((table_name, rows))
        return len(rows)

    def batch_create_records(self, table_name, rows):
        self.created.append((table_name, rows))
        return [f"rec-created-{index}" for index in range(len(rows))]

    def delete_record_ids(self, table_name, ids):
        self.deleted.append((table_name, ids))
        return len(ids)


def event(identifier, key, operation="upsert", name="Ana"):
    return {
        "id": identifier,
        "table_name": "Workers",
        "key_field": "Worker Key",
        "key_value": key,
        "operation": operation,
        "fields": {"Worker Key": key, "Name": name} if operation == "upsert" else {},
    }


def work_event(identifier, table_name, key, fields=None, operation="upsert"):
    return {
        "id": identifier,
        "table_name": table_name,
        "key_field": (
            "Work Day Key" if table_name == "Work Days" else "Location Entry Key"
        ),
        "key_value": key,
        "operation": operation,
        "fields": fields or {},
    }


class LarkSyncTests(unittest.TestCase):
    def test_cost_center_fields_are_normalized_for_lark_types(self):
        self.assertEqual(
            normalize_mirror_fields(
                "Cost Centers",
                {
                    "Cost Center ID": "21-13-0010",
                    "Name": "Framing",
                    "Active": "true",
                    "Display Order": "4",
                },
            ),
            {
                "Cost Center ID": "21-13-0010",
                "Name": "Framing",
                "Active": True,
                "Display Order": 4,
            },
        )

    def test_invalid_cost_center_number_identifies_the_field(self):
        with self.assertRaisesRegex(
            Exception, r"Cost Centers\.Display Order must be a number"
        ):
            normalize_mirror_fields(
                "Cost Centers",
                {"Cost Center ID": "21-13-0010", "Display Order": "n/a"},
            )

    def test_latest_event_wins_for_the_same_key(self):
        output = latest_events([event(1, "7", name="Old"), event(2, "7", name="New")])
        self.assertEqual(output[("Workers", "7")]["fields"]["Name"], "New")

    def test_sync_updates_creates_and_deletes_without_listing_lark(self):
        database = FakeDatabase(
            [event(1, "7"), event(2, "8"), event(3, "9", "delete")],
            mappings={"7": "rec-seven", "9": "rec-nine"},
        )
        mirror = FakeLark()
        with (
            patch.dict(
                os.environ,
                {"DATA_BACKEND": "postgres", "LARK_MIRROR_ENABLED": "true"},
            ),
            patch("api._lark_sync.PostgresBase", return_value=database),
            patch("api._lark_sync.LarkBase", return_value=mirror),
        ):
            result = synchronize_lark()
        self.assertEqual(database.completed, [1, 2, 3])
        self.assertFalse(database.failed)
        self.assertEqual(mirror.updated[0][1][0]["record_id"], "rec-seven")
        self.assertEqual(mirror.created[0][1][0]["Worker Key"], "8")
        self.assertEqual(mirror.deleted, [("Workers", ["rec-nine"])])
        self.assertEqual(database.saved_mappings, {"8": "rec-created-0"})
        self.assertEqual(database.deleted_mappings, ["9"])
        self.assertEqual(result["processed"], 3)

    def test_failed_table_returns_events_to_the_retry_queue(self):
        database = FakeDatabase([event(4, "7")], mappings={"7": "rec-seven"})
        mirror = FakeLark()
        mirror.batch_update_record_ids = lambda *_args: (_ for _ in ()).throw(
            RuntimeError("temporary")
        )
        with (
            patch.dict(
                os.environ,
                {"DATA_BACKEND": "postgres", "LARK_MIRROR_ENABLED": "true"},
            ),
            patch("api._lark_sync.PostgresBase", return_value=database),
            patch("api._lark_sync.LarkBase", return_value=mirror),
        ):
            result = synchronize_lark()
        self.assertFalse(database.completed)
        self.assertEqual(database.failed[0][0], [4])
        self.assertEqual(result["failed_tables"], ["Workers"])

    def test_work_day_and_locations_are_projected_to_one_work_log_row(self):
        key = "7|2026-07-24"
        day = {
            "Work Day Key": key,
            "Worker Key": "7",
            "Worker Name": "Ana",
            "Work Date": 1784876400000,
            "Status": "worked",
            "Total Hours": 8,
            "Overtime Hours": 0,
        }
        location = {
            "Work Day Key": key,
            "Location": "444 Pocatello",
            "Start Time": "08:30",
            "End Time": "16:30",
            "Regular Hours": 8,
            "Overtime Hours": 0,
            "Cost Center ID": "100",
            "Cost Center Name": "Framing",
            "Display Order": 1,
        }
        database = FakeDatabase(
            [
                work_event(5, "Work Days", key, day),
                work_event(
                    6,
                    "Location Entries",
                    f"{key}|1|1",
                    location,
                ),
            ],
            work_rows=([day], [location]),
        )
        mirror = FakeLark()
        with (
            patch.dict(
                os.environ,
                {"DATA_BACKEND": "postgres", "LARK_MIRROR_ENABLED": "true"},
            ),
            patch("api._lark_sync.PostgresBase", return_value=database),
            patch("api._lark_sync.LarkBase", return_value=mirror),
        ):
            result = synchronize_lark()
        self.assertEqual(database.completed, [5, 6])
        self.assertEqual(mirror.created[0][0], "Work Log")
        row = mirror.created[0][1][0]
        self.assertEqual(row["Entry Key"], key)
        self.assertEqual(
            row["Normalized Entry"],
            "444 Pocatello [08:30-16:30 | 8h | CC: 100 Framing (8h)]",
        )
        self.assertEqual(result["processed"], 2)

    def test_deleted_work_day_deletes_consolidated_row(self):
        key = "7|2026-07-24"
        database = FakeDatabase(
            [work_event(7, "Work Days", key, operation="delete")],
            mappings={key: "rec-work-log"},
        )
        mirror = FakeLark()
        with (
            patch.dict(
                os.environ,
                {"DATA_BACKEND": "postgres", "LARK_MIRROR_ENABLED": "true"},
            ),
            patch("api._lark_sync.PostgresBase", return_value=database),
            patch("api._lark_sync.LarkBase", return_value=mirror),
        ):
            synchronize_lark()
        self.assertEqual(mirror.deleted, [("Work Log", ["rec-work-log"])])
        self.assertEqual(database.deleted_mappings, [key])


if __name__ == "__main__":
    unittest.main()
