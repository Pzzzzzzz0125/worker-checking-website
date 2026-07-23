import unittest

from api._lark import LarkAPIError
from api._lark_drive import exact_file, file_name, file_token, normalized_file_name


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


if __name__ == "__main__":
    unittest.main()
