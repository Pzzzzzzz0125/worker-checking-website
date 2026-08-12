import unittest
from unittest.mock import patch

from report_handlers.schedule import (
    _conflict_message,
    _notification_targets,
    _notify_conflicts,
    _selected_dates,
)


class ScheduleDateSelectionTests(unittest.TestCase):
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
