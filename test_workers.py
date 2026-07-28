import os
import time
import unittest
from unittest.mock import patch

from api._shared import sign_payload
from report_handlers.workers import (
    access_status,
    create_worker,
    list_workers,
    payroll_access_status,
    remove_worker,
    update_worker,
)


def record(record_id, **fields):
    return {"record_id": record_id, "fields": fields}


class FakeBase:
    def __init__(self):
        self.saved = None
        self.deleted = []
        self.work_days = []
        self.payroll_checks = []
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
        if table_name == "Workers":
            return self.rows
        if table_name == "Work Days":
            return self.work_days
        return self.payroll_checks

    def set_by_key(self, table_name, key_field, key, fields):
        self.saved = (table_name, key_field, key, fields)
        match = next(
            (
                row for row in self.rows
                if row["fields"].get("Worker Key") == key
            ),
            None,
        )
        if match:
            match["fields"].update(fields)
            return {"created": False, "record_id": match["record_id"]}
        self.rows.append(record(f"worker-{key}", **fields))
        return {"created": True, "record_id": f"worker-{key}"}

    def delete_record_ids(self, table_name, record_ids):
        self.deleted.extend(record_ids)
        self.rows = [
            row for row in self.rows
            if row["record_id"] not in record_ids
        ]
        return len(record_ids)


class WorkerProfileTests(unittest.TestCase):
    def test_lark_admin_bypasses_password(self):
        request = type("Request", (), {"headers": {"cookie": ""}})()
        with patch.dict(
            "os.environ",
            {"LARK_ADMIN_OPEN_IDS": "ou-admin", "WORKER_ADMIN_PASSWORD": "secret"},
            clear=False,
        ):
            result = access_status(request, {"sub": "ou-admin"})
        self.assertTrue(result["authorized"])
        self.assertEqual(result["access_type"], "lark_admin")
        self.assertTrue(result["password_configured"])

    def test_payroll_grant_also_authorizes_location_cost_access(self):
        environment = {
            "SESSION_SECRET": "test-session-secret-that-is-long-enough",
            "PAYROLL_PASSWORD": "shared-sensitive-report-password",
            "LARK_ADMIN_OPEN_IDS": "",
        }
        with patch.dict(os.environ, environment, clear=False):
            grant = sign_payload(
                {
                    "sub": "ou-supervisor",
                    "scope": "payroll-check",
                    "iat": int(time.time()),
                }
            )
            request = type(
                "Request",
                (),
                {"headers": {"cookie": f"payroll_access_session={grant}"}},
            )()
            access = payroll_access_status(request, {"sub": "ou-supervisor"})
        self.assertTrue(access["authorized"])
        self.assertEqual(access["access_type"], "password")

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
        self.assertEqual(base.saved[3]["Worker Key"], "7")
        self.assertEqual(base.saved[3]["Normalized Name"], "christopher cong")
        self.assertFalse(base.saved[3]["Active"])

    def test_create_worker_assigns_next_key_and_default_order(self):
        base = FakeBase()
        created = create_worker(
            base,
            {
                "name": "New Worker",
                "worker_type": "W2",
                "active": True,
                "daily_rate": 280,
                "aliases": "",
                "notes": "",
            },
        )
        self.assertEqual(created["worker_key"], "8")
        self.assertEqual(created["display_order"], 3)
        self.assertEqual(base.saved[3]["Worker Key"], "8")

    def test_remove_worker_without_history_deletes_master_record(self):
        base = FakeBase()
        result = remove_worker(base, {"worker_key": "7"})
        self.assertEqual(result["mode"], "deleted")
        self.assertEqual(base.deleted, ["worker-7"])

    def test_remove_worker_with_history_archives_worker(self):
        base = FakeBase()
        base.work_days = [
            record(
                "day-1",
                **{"Work Day Key": "7|2026-07-01", "Worker Key": "7"},
            )
        ]
        result = remove_worker(base, {"worker_key": "7"})
        self.assertEqual(result["mode"], "archived")
        self.assertEqual(result["history_records"], 1)
        self.assertFalse(base.saved[3]["Active"])
        self.assertEqual(base.deleted, [])

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
