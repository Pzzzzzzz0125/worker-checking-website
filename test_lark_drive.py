import unittest
from unittest.mock import patch

from api._lark import LarkAPIError
from api import _lark_drive
from api._lark_drive import download_file, exact_file, file_name, file_token, normalized_file_name


class LarkDriveTests(unittest.TestCase):
    def test_exact_file_accepts_current_drive_fields(self):
        item = {"name": "Workers.xlsx", "token": "file-token", "type": "file"}
        self.assertIs(exact_file([item], "Workers.xlsx"), item)
        self.assertEqual(file_name(item), "Workers.xlsx")
        self.assertEqual(file_token(item), "file-token")

    def test_filename_match_tolerates_lark_punctuation_and_extension_changes(self):
        item = {
            "name": "2026 Worker’s information – location  standardized",
            "token": "file-token",
        }
        expected = "2026 Worker's information - location standardized.xlsx"
        self.assertIs(exact_file([item], expected), item)
        self.assertEqual(
            normalized_file_name(item["name"]),
            normalized_file_name(expected),
        )

    def test_exact_file_rejects_missing_and_duplicate_names(self):
        with self.assertRaises(LarkAPIError) as missing:
            exact_file([{"name": "Payroll.xlsx", "token": "one"}], "Workers.xlsx")
        self.assertEqual(missing.exception.status, 404)
        self.assertIn("Payroll.xlsx", str(missing.exception))
        with self.assertRaises(LarkAPIError) as duplicate:
            exact_file(
                [
                    {"name": "Workers.xlsx", "token": "one"},
                    {"name": "Workers.xlsx", "token": "two"},
                ],
                "Workers.xlsx",
            )
        self.assertEqual(duplicate.exception.status, 409)

    def test_drive_file_uses_direct_file_download(self):
        with patch.object(_lark_drive, "lark_download", return_value=b"xlsx") as download:
            result = download_file({"token": "box-token", "type": "file"}, "tenant")
        self.assertEqual(result, b"xlsx")
        download.assert_called_once_with(
            "/drive/v1/files/box-token/download", token="tenant"
        )

    def test_online_sheet_is_exported_to_xlsx(self):
        responses = [
            {"data": {"ticket": "ticket-one"}},
            {"data": {"result": {"job_status": 1}}},
            {"data": {"result": {"job_status": 0, "file_token": "exported"}}},
        ]
        with (
            patch.object(_lark_drive, "lark_api", side_effect=responses) as api,
            patch.object(_lark_drive, "lark_download", return_value=b"xlsx") as download,
            patch.object(_lark_drive.time, "sleep"),
        ):
            result = download_file({"token": "sheet-token", "type": "sheet"}, "tenant")
        self.assertEqual(result, b"xlsx")
        self.assertEqual(api.call_count, 3)
        download.assert_called_once_with(
            "/drive/v1/export_tasks/file/exported/download", token="tenant"
        )


if __name__ == "__main__":
    unittest.main()
