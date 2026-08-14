import unittest
import io
from pathlib import Path
from unittest.mock import patch

from report_handlers import cost_codes
from report_handlers.cost_codes import (
    changed_rows, cost_code_source, cron_authorized, read_sheet_cost_centers,
    resolve_source,
)
from xlsx_workbook import fill_template_workbook, read_cost_centers


class CostCodeSourceTests(unittest.TestCase):
    def test_daily_cron_requires_exact_bearer_secret(self):
        self.assertTrue(cron_authorized("Bearer secret-value", "secret-value"))
        self.assertFalse(cron_authorized("secret-value", "secret-value"))
        self.assertFalse(cron_authorized("Bearer wrong", "secret-value"))
        self.assertFalse(cron_authorized("Bearer anything", ""))

    def test_parses_separate_lark_sheet_and_file_links(self):
        sheet = cost_code_source("https://tenant.larksuite.com/sheets/sht123?sheet=abc")
        file = cost_code_source("https://tenant.larksuite.com/file/box456")
        self.assertEqual(sheet, {
            "token": "sht123", "type": "sheet", "name": "Connected Cost Code source",
            "sheet_id": "abc",
        })
        self.assertEqual(file["token"], "box456")
        self.assertEqual(file["type"], "file")

    def test_resolves_wiki_node_to_its_sheet_token(self):
        wiki = cost_code_source(
            "https://tenant.larksuite.com/wiki/O9cZwyfbeiesElkgdYtlG6MDg0c?sheet=2IdR2F"
        )
        self.assertEqual(wiki["type"], "wiki")
        self.assertEqual(wiki["sheet_id"], "2IdR2F")
        with patch.object(cost_codes, "lark_api", return_value={
            "data": {"node": {"obj_token": "sht-real", "obj_type": "sheet"}},
        }) as api:
            resolved = resolve_source(wiki, "tenant-token")
        self.assertEqual(resolved["token"], "sht-real")
        self.assertEqual(resolved["type"], "sheet")
        self.assertEqual(resolved["sheet_id"], "2IdR2F")
        api.assert_called_once_with(
            "GET", "/wiki/v2/spaces/get_node", token="tenant-token",
            query={"token": "O9cZwyfbeiesElkgdYtlG6MDg0c"},
        )

    def test_reads_selected_sheet_columns_b_and_c(self):
        with patch.object(cost_codes, "lark_api", return_value={
            "data": {"valueRange": {"values": [
                ["", "ID", "Name"], ["", "01-01-0010", "General labor"],
                ["", "02-02-0020", "Equipment"],
            ]}},
        }) as api:
            rows = read_sheet_cost_centers({
                "token": "sht-real", "type": "sheet", "sheet_id": "2IdR2F",
            }, "tenant-token")
        self.assertEqual(rows[1], {"id": "02-02-0020", "name": "Equipment"})
        api.assert_called_once_with(
            "GET",
            "/sheets/v2/spreadsheets/sht-real/values/2IdR2F%21A1%3AC5000",
            token="tenant-token",
        )

    def test_reads_new_labor_cost_code_sheet_layout(self):
        with patch.object(cost_codes, "lark_api", return_value={
            "data": {"valueRange": {"values": [
                ["Cost Code", "Description", "中文描述"],
                ["01-56-0010", "Temp Fencing Labor", "临时围栏安装 人工"],
                ["03-31-0010", "Slab on grade Labor", "板式基础 人工"],
            ]}},
        }):
            rows = read_sheet_cost_centers({
                "token": "sht-real", "type": "sheet", "sheet_id": "labor",
            }, "tenant-token")
        self.assertEqual(rows, [
            {"id": "01-56-0010", "name": "Temp Fencing Labor"},
            {"id": "03-31-0010", "name": "Slab on grade Labor"},
        ])

    def test_exported_workbook_reads_new_labor_layout(self):
        output = io.BytesIO()
        fill_template_workbook(
            Path(__file__).parent / "templates" / "Worker Compensation Auditor Report.xlsx",
            output,
            cell_updates={"Sheet1": {
                "A1": "Cost Code", "B1": "Description",
                "A2": "06-11-0010", "B2": "Framing Labor",
            }},
        )
        self.assertEqual(read_cost_centers(io.BytesIO(output.getvalue())), [
            {"id": "06-11-0010", "name": "Framing Labor"},
        ])

    def test_reads_numeric_and_rich_text_sheet_cells_without_crashing(self):
        with patch.object(cost_codes, "lark_api", return_value={
            "data": {"valueRange": {"values": [
                ["ID", "Name"],
                [1010, "Numeric code"],
                [2020.0, [{"text": "Rich"}, {"text": "name"}]],
                [float("nan"), "Ignored invalid number"],
            ]}},
        }):
            rows = read_sheet_cost_centers({
                "token": "sht-real", "type": "sheet", "sheet_id": "2IdR2F",
            }, "tenant-token")
        self.assertEqual(rows, [
            {"id": "1010", "name": "Numeric code"},
            {"id": "2020", "name": "Rich name"},
        ])

    def test_only_new_or_changed_codes_are_written(self):
        existing = [
            {"record_id": "one", "fields": {
                "Cost Center ID": "01-01", "Name": "Labor", "Active": True,
                "Display Order": 1,
            }},
            {"record_id": "two", "fields": {
                "Cost Center ID": "02-01", "Name": "Old name", "Active": True,
                "Display Order": 2,
            }},
            {"record_id": "old", "fields": {
                "Cost Center ID": "99-01", "Name": "Outdated code", "Active": True,
                "Display Order": 99,
            }},
        ]
        source = [
            {"Cost Center ID": "01-01", "Name": "Labor", "Active": True, "Display Order": 1},
            {"Cost Center ID": "02-01", "Name": "New name", "Active": True, "Display Order": 2},
            {"Cost Center ID": "03-01", "Name": "Equipment", "Active": True, "Display Order": 3},
        ]
        rows, counts = changed_rows(source, existing)
        self.assertEqual([row["Cost Center ID"] for row in rows], ["02-01", "03-01", "99-01"])
        self.assertFalse(rows[-1]["Active"])
        self.assertEqual(counts, {
            "source_rows": 3, "database_rows": 3, "added": 1,
            "updated": 1, "deactivated": 1, "unchanged": 1,
        })


if __name__ == "__main__":
    unittest.main()
