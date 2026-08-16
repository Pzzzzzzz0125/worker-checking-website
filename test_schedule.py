import unittest
from unittest.mock import patch

from report_handlers.schedule import (
    _conflict_message,
    _conflict_reason,
    _notification_targets,
    _notify_conflicts,
    _payload,
    _save,
    _selected_dates,
)


class ScheduleDateSelectionTests(unittest.TestCase):
    def test_schedule_payload_no_longer_requires_work_task(self):
        fields = _payload(
            {
                "schedule_date": "2026-08-12",
                "site": "850 Villa",
                "cost_code_ids": ["06-11-0010"],
                "start_time": "",
                "end_time": "",
            },
            {"worker_key": "1", "worker_name": "Ana"},
            {"06-11-0010": "Framing Labor"},
        )
        self.assertEqual(fields["Task"], "")

    def test_legacy_task_does_not_make_a_duplicate_schedule_distinct(self):
        candidate = {
            "schedule_key": "new", "worker_key": "1", "worker_name": "Ana",
            "schedule_date": "2026-08-12", "site": "850 Villa",
            "task": "", "start_time": "08:30", "end_time": "16:30",
            "status": "confirmed",
        }
        existing = [{
            **candidate, "schedule_key": "old", "task": "Legacy framing",
        }]
        with self.assertRaisesRegex(ValueError, "already exists"):
            _conflict_reason(candidate, existing)

    @patch("report_handlers.schedule.schedule_notification_recipients", return_value=[])
    def test_conflict_preview_does_not_write_before_manager_confirmation(self, _recipients):
        class FakeBase:
            def __init__(self):
                self.writes = []

            def records(self, table, cache_seconds=0):
                if table == "Workers":
                    return [{"record_id": "w1", "fields": {"Worker Key": "1", "Name": "Ana", "Active": True}}]
                if table == "Cost Centers":
                    return [{"record_id": "c1", "fields": {"Cost Center ID": "06-11-0010", "Name": "Framing Labor", "Active": True}}]
                if table == "Schedules":
                    return [{"record_id": "s1", "fields": {
                        "Schedule Key": "existing", "Worker Key": "1", "Worker Name": "Ana",
                        "Schedule Date": "2026-08-12", "Site": "850 Villa",
                        "Cost Code IDs": "06-11-0010", "Cost Code Names": "Framing Labor",
                        "Task": "", "Start Time": "", "End Time": "", "Status": "confirmed",
                    }}]
                return []

            def set_by_key(self, *args):
                self.writes.append(args)
                return {"created": True}

        base = FakeBase()
        result = _save(base, {
            "action": "save", "schedule_date": "2026-08-12", "worker_key": "1",
            "site": "912 Connie Dr", "cost_code_ids": ["06-11-0010"],
            "start_time": "", "end_time": "", "confirm_conflicts": False,
        }, {"sub": "manager", "name": "Manager"})
        self.assertTrue(result["requires_conflict_approval"])
        self.assertEqual(base.writes, [])
        self.assertEqual(result["conflicts"][0]["existing"][0]["site"], "850 Villa")

    def test_notification_targets_always_include_admins_and_selected_managers(self):
        available = [
            {"open_id": "admin", "name": "Admin", "required": True},
            {"open_id": "manager-a", "name": "Manager A", "required": False},
            {"open_id": "manager-b", "name": "Manager B", "required": False},
        ]
        selected = _notification_targets(
            {"notification_recipient_ids": ["manager-b"]},
            available,
        )
        self.assertEqual(
            {recipient["open_id"] for recipient in selected},
            {"admin", "manager-b"},
        )

    def test_unknown_notification_recipient_is_rejected(self):
        with self.assertRaises(ValueError):
            _notification_targets(
                {"notification_recipient_ids": ["not-a-manager"]},
                [{"open_id": "admin", "required": True}],
            )

    @patch("report_handlers.schedule.lark_api")
    @patch("report_handlers.schedule.tenant_access_token", return_value="token")
    def test_conflict_notification_is_sent_to_each_validated_recipient(
        self,
        _token,
        mocked_api,
    ):
        schedules = [
            {
                "worker_name": "Ana",
                "schedule_date": "2026-08-12",
                "site": "850 Villa",
                "task": "Framing",
                "cost_code_names": ["Labor"],
                "start_time": "08:30",
                "end_time": "16:30",
            }
        ]
        conflicts = [
            {"schedule_date": "2026-08-12", "reason": "Ana overlaps another Site."}
        ]
        recipients = [
            {"open_id": "admin", "name": "Admin"},
            {"open_id": "manager", "name": "Manager"},
        ]
        result = _notify_conflicts(
            recipients, schedules, conflicts, "Foreman"
        )
        self.assertEqual(result["sent"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(mocked_api.call_count, 2)
        message_body = mocked_api.call_args_list[0].kwargs["body"]
        self.assertIn("Schedule conflict needs approval", message_body["content"])
        self.assertIn("850 Villa", message_body["content"])

    def test_conflict_message_contains_review_context(self):
        message = _conflict_message(
            [{
                "worker_name": "Ana", "schedule_date": "2026-08-12",
                "site": "850 Villa", "task": "Framing",
                "cost_code_names": ["Labor"], "start_time": "", "end_time": "",
            }],
            [{"schedule_date": "2026-08-12", "reason": "Overlap"}],
            "Foreman",
        )
        self.assertIn("Submitted by: Foreman", message)
        self.assertIn("Time: not set", message)
        self.assertNotIn("Task:", message)
        self.assertIn("/#schedule", message)

    def test_single_day_is_one_date(self):
        self.assertEqual(
            _selected_dates({"schedule_date": "2026-08-10", "schedule_end_date": "2026-08-10"}),
            ["2026-08-10"],
        )

    def test_range_expands_each_day(self):
        self.assertEqual(
            _selected_dates({"schedule_date": "2026-08-10", "schedule_end_date": "2026-08-12"}),
            ["2026-08-10", "2026-08-11", "2026-08-12"],
        )

    def test_calendar_selection_is_sorted_and_deduplicated(self):
        self.assertEqual(
            _selected_dates({"schedule_dates": ["2026-08-12", "2026-08-10", "2026-08-12"]}),
            ["2026-08-10", "2026-08-12"],
        )

    def test_calendar_selection_has_31_date_limit(self):
        with self.assertRaises(ValueError):
            _selected_dates({"schedule_dates": [f"2026-08-{day:02d}" for day in range(1, 33)]})


if __name__ == "__main__":
    unittest.main()
