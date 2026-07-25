import unittest
from unittest.mock import patch

from api import _lark_base
from api._lark import LarkAPIError
from api._lark_base import LarkBase


class LarkBaseWriteTests(unittest.TestCase):
    def base(self):
        base = LarkBase.__new__(LarkBase)
        base.token = "tenant"
        base.app_token = "app"
        base._table_ids = {"Workers": "tbl-workers"}
        return base

    def test_create_missing_batches_and_preserves_existing_records(self):
        base = self.base()
        rows = [{"Worker Key": str(index), "Name": f"Worker {index}"} for index in range(1, 503)]
        with (
            patch.object(base, "records", return_value=[{"fields": {"Worker Key": "1"}}]),
            patch.object(_lark_base, "lark_api", return_value={"data": {}}) as api,
        ):
            result = base.create_missing("Workers", "Worker Key", rows)
        self.assertEqual(result, {"expected": 502, "created": 501, "already_present": 1})
        self.assertEqual(api.call_count, 2)
        self.assertEqual(len(api.call_args_list[0].kwargs["body"]["records"]), 500)
        self.assertEqual(len(api.call_args_list[1].kwargs["body"]["records"]), 1)

    def test_create_missing_rejects_duplicate_source_keys(self):
        base = self.base()
        with (
            patch.object(base, "records", return_value=[]),
            self.assertRaises(LarkAPIError),
        ):
            base.create_missing(
                "Workers",
                "Worker Key",
                [{"Worker Key": "1"}, {"Worker Key": "1"}],
            )

    def test_direct_create_returns_record_ids(self):
        base = self.base()
        with patch.object(
            _lark_base,
            "lark_api",
            return_value={
                "data": {
                    "records": [
                        {"record_id": "rec-one"},
                        {"record_id": "rec-two"},
                    ]
                }
            },
        ):
            ids = base.batch_create_records(
                "Workers",
                [
                    {"Worker Key": "1", "Name": "One"},
                    {"Worker Key": "2", "Name": "Two"},
                ],
            )
        self.assertEqual(ids, ["rec-one", "rec-two"])


if __name__ == "__main__":
    unittest.main()
