import os
import unittest
from unittest.mock import patch

from api._lark_sync import latest_events, synchronize_lark


class FakeDatabase:
    def __init__(self, events, mappings=None):
        self.events = events
        self.mappings = mappings or {}
        self.completed = []
        self.failed = []
        self.saved_mappings = {}
        self.deleted_mappings = []

    def claim_sync_events(self, _limit):
        return self.events

    def mirror_record_ids(self, _table_name, keys):
        return {key: self.mappings[key] for key in keys if key in self.mappings}

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


class LarkSyncTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
