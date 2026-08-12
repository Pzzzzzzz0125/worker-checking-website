import unittest
from unittest.mock import patch

from api._lark_sheet import (
    HEADER_ROW_HEIGHT,
    LarkWorkbook,
    WORK_CELL_HEIGHT,
    WORK_CELL_WIDTH,
    WORKER_COLUMN_WIDTH,
    assign_worker_rows,
    column_name,
    pay_period,
    sheet_cell_text,
)


class LarkSheetTests(unittest.TestCase):
    def test_pay_periods_match_half_month_payroll_layout(self):
        first = pay_period("2026-02-15")
        second = pay_period("2026-02-16")
        self.assertEqual(first.title, "2026-02 · 01-15")
        self.assertEqual(first.start.isoformat(), "2026-02-01")
        self.assertEqual(first.end.isoformat(), "2026-02-15")
        self.assertEqual(second.title, "2026-02 · 16-28")
        self.assertEqual(second.end.isoformat(), "2026-02-28")

    def test_column_names_cover_period_grid(self):
        self.assertEqual(column_name(1), "A")
        self.assertEqual(column_name(2), "B")
        self.assertEqual(column_name(26), "Z")
        self.assertEqual(column_name(27), "AA")

    def test_worker_rows_remain_stable_when_a_worker_is_added(self):
        workers = [
            {"key": "7", "name": "Ana", "active": True, "order": 1},
            {"key": "8", "name": "Ben", "active": True, "order": 2},
        ]
        rows = assign_worker_rows(workers, {"7": 4})
        self.assertEqual(rows["7"], 4)
        self.assertEqual(rows["8"], 5)

    def test_cell_contains_structured_work_and_metadata(self):
        text = sheet_cell_text(
            {
                "Status": "worked",
                "Normalized Entry": (
                    "444 Pocatello [08:30-16:30 | 8h | CC: 100 Framing (8h)]"
                ),
                "Total Hours": 10,
                "Regular Hours": 8,
                "Overtime Hours": 2,
                "Extra Pay": 20,
                "Notes": "Material delivery",
                "Source": "web-entry",
                "Confidence": "high",
            }
        )
        self.assertIn("WORKED | 444 Pocatello", text)
        self.assertIn("TOTAL 10h | REG 8h | OT 2h | EXTRA $20", text)
        self.assertIn("NOTE: Material delivery", text)
        self.assertIn("SOURCE web-entry | CONFIDENCE high", text)

    def test_incremental_sync_targets_worker_date_cell(self):
        with patch("api._lark_sheet.tenant_access_token", return_value="token"):
            workbook = LarkWorkbook("spreadsheet")
        captured = []
        workbook.ensure_periods = lambda periods: {
            period.key: "sheet-one" for period in periods
        }
        workbook.write_cells = lambda cells: captured.extend(cells)
        result = workbook.sync_work_rows(
            [{"key": "7", "name": "Ana", "active": True, "order": 1}],
            [
                {
                    "Worker Key": "7",
                    "Work Date": "2026-07-02",
                    "Status": "worked",
                    "Normalized Entry": "444",
                    "Total Hours": 8,
                    "Regular Hours": 8,
                }
            ],
            [],
            {"worker_rows": {"7": 2}},
        )
        self.assertIn(("sheet-one", "C2", sheet_cell_text({
            "Worker Key": "7",
            "Work Date": "2026-07-02",
            "Status": "worked",
            "Normalized Entry": "444",
            "Total Hours": 8,
            "Regular Hours": 8,
        })), captured)
        self.assertEqual(result["updated_cells"], len(captured))

    @patch("api._lark_sheet.lark_api")
    @patch("api._lark_sheet.tenant_access_token", return_value="token")
    def test_value_ranges_use_sheet_title_not_internal_sheet_id(
        self,
        _token,
        mocked_api,
    ):
        workbook = LarkWorkbook("spreadsheet")
        workbook._sheet_titles_by_id = {"88348e": "2026-01 · 01-15"}

        workbook.write_cells([("88348e", "A1", "Worker")])
        workbook.write_range("88348e", "A1:B2", [["Worker", "01/01"]])
        workbook.style_range("88348e", "A1:B1", {"font": {"bold": True}})

        ranges = [
            call.kwargs["body"]["valueRanges"][0]["range"]
            if "valueRanges" in call.kwargs["body"]
            else call.kwargs["body"]["valueRange"]["range"]
            if "valueRange" in call.kwargs["body"]
            else call.kwargs["body"]["appendStyle"]["range"]
            for call in mocked_api.call_args_list
        ]
        self.assertEqual(
            ranges,
            [
                "'2026-01 · 01-15'!A1",
                "'2026-01 · 01-15'!A1:B2",
                "'2026-01 · 01-15'!A1:B1",
            ],
        )

    @patch("api._lark_sheet.lark_api")
    @patch("api._lark_sheet.tenant_access_token", return_value="token")
    def test_readable_layout_widens_columns_and_rows(
        self,
        _token,
        mocked_api,
    ):
        workbook = LarkWorkbook("spreadsheet")
        workbook.apply_readable_layout("sheet-one", 15, 54)
        dimensions = [call.kwargs["body"] for call in mocked_api.call_args_list]
        self.assertEqual(
            dimensions[0]["dimensionProperties"]["fixedSize"],
            WORKER_COLUMN_WIDTH,
        )
        self.assertEqual(
            dimensions[1]["dimensionProperties"]["fixedSize"],
            WORK_CELL_WIDTH,
        )
        self.assertEqual(
            dimensions[2]["dimensionProperties"]["fixedSize"],
            HEADER_ROW_HEIGHT,
        )
        self.assertEqual(
            dimensions[3]["dimensionProperties"]["fixedSize"],
            WORK_CELL_HEIGHT,
        )
        self.assertEqual(dimensions[1]["dimension"]["endIndex"], 16)
        self.assertEqual(dimensions[3]["dimension"]["endIndex"], 54)


if __name__ == "__main__":
    unittest.main()
