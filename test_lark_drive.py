import unittest

from api._lark import LarkAPIError
from api._lark_drive import exact_file, file_name, file_token


class LarkDriveTests(unittest.TestCase):
    def test_exact_file_accepts_current_drive_fields(self):
        item = {"name": "Workers.xlsx", "token": "file-token", "type": "file"}
        self.assertIs(exact_file([item], "Workers.xlsx"), item)
        self.assertEqual(file_name(item), "Workers.xlsx")
        self.assertEqual(file_token(item), "file-token")

    def test_exact_file_rejects_missing_and_duplicate_names(self):
        with self.assertRaises(LarkAPIError) as missing:
            exact_file([], "Workers.xlsx")
        self.assertEqual(missing.exception.status, 404)
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
