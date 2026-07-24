import os
import unittest
from unittest.mock import patch

from api._data_store import DataStore
from api._lark_base import LarkBase
from api._postgres_base import PostgresBase, _matches_filter


class PostgresAdapterTests(unittest.TestCase):
    def test_date_and_worker_filters_match_record_shape(self):
        record = {
            "record_id": "day-1",
            "fields": {
                "Worker Key": "7",
                "Work Date": "2026-07-14",
            },
        }
        formula = (
            'AND(CurrentValue.[Work Date]>=TODATE("2026-07-01"),'
            'CurrentValue.[Work Date]<=TODATE("2026-07-15"),'
            'CurrentValue.[Worker Key]="7")'
        )
        self.assertTrue(_matches_filter(record, formula))
        self.assertFalse(
            _matches_filter(
                record,
                'CurrentValue.[Work Date]>=TODATE("2026-07-15")',
            )
        )

    def test_backend_selection_is_explicit(self):
        with patch.dict(os.environ, {"DATA_BACKEND": "postgres"}):
            self.assertIsInstance(DataStore(), PostgresBase)
        with patch.dict(os.environ, {"DATA_BACKEND": "lark"}):
            base = LarkBase.__new__(LarkBase)
            with patch("api._data_store.LarkBase", return_value=base):
                self.assertIs(DataStore(), base)


if __name__ == "__main__":
    unittest.main()
