import io
import unittest
from datetime import date
from zipfile import ZipFile

from report_handlers.exports import (
    AUDITOR_TEMPLATE,
    INVOICE_TEMPLATE,
    _filters,
    auditor_rows,
    invoice_values,
)
from xlsx_workbook import (
    _shared_strings,
    fill_template_workbook,
    sheet_rows,
    workbook_sheets,
)


def sample_data():
    return {
        "workers": {
            "1": {
                "id": 1,
                "key": "1",
                "name": "Alex Worker",
                "worker_type": "W2",
                "daily_rate": 320,
            }
        },
        "days": [
            {
                "work_day_id": "1|2026-07-06",
                "worker_id": 1,
                "worker_key": "1",
                "worker_name": "Alex Worker",
                "date": "2026-07-06",
                "status": "worked",
                "total_hours": 10,
                "extra_pay": 0,
                "locations": [
                    {
                        "name": "100 Main St",
                        "hours": 6,
                        "start_time": "08:00",
                        "end_time": "14:00",
                        "cost_centers": [{"id": "CC-1", "name": "Framing"}],
                    },
                    {
                        "name": "200 Oak Ave",
                        "hours": 4,
                        "start_time": "14:00",
                        "end_time": "18:00",
                        "cost_centers": [{"id": "CC-2", "name": "Finish"}],
                    },
                ],
            }
        ],
        "checks": {},
    }


class ExportTests(unittest.TestCase):
    def test_auditor_report_allocates_regular_and_overtime_to_sites(self):
        rows = auditor_rows(
            sample_data(),
            date(2026, 7, 6),
            date(2026, 7, 6),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][2], "100 Main St")
        self.assertEqual(rows[0][3], "Framing (CC-1)")
        self.assertAlmostEqual(sum(float(row[6]) for row in rows), 10)
        self.assertAlmostEqual(sum(float(row[7]) for row in rows), 8)
        self.assertAlmostEqual(sum(float(row[8]) for row in rows), 2)

    def test_auditor_accepts_multiple_worker_and_site_filters(self):
        start, end, worker_keys, sites = _filters({
            "from": "2026-07-01",
            "to": "2026-07-31",
            "worker_ids": ["1", "1"],
            "sites": ["100 Main St", "200 Oak Ave"],
        })
        self.assertEqual((start, end), (date(2026, 7, 1), date(2026, 7, 31)))
        self.assertEqual(worker_keys, ["1"])
        self.assertEqual(sites, ["100 Main St", "200 Oak Ave"])
        rows = auditor_rows(
            sample_data(),
            date(2026, 7, 6),
            date(2026, 7, 6),
            worker_keys=["1"],
            sites=["200 Oak Ave"],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "200 Oak Ave")

    def test_invoice_uses_customer_billing_rate_not_worker_salary(self):
        values = invoice_values(
            sample_data(),
            {
                "bill_to": "Example Customer",
                "invoice_number": "INV-42",
                "invoice_date": "2026-07-07",
                "payment_due": "2026-08-06",
                "billing_rate": 125,
            },
            date(2026, 7, 6),
            date(2026, 7, 6),
            sites=["100 Main St"],
        )
        self.assertEqual(values["F3"], "INV-42")
        self.assertEqual(values["F8"], "100 Main St")
        self.assertEqual(values["F16"], 125)
        self.assertEqual(values["G16"], 750)
        self.assertNotEqual(values["G16"], 320)

    def test_templates_generate_valid_xlsx_packages(self):
        auditor_output = io.BytesIO()
        fill_template_workbook(
            AUDITOR_TEMPLATE,
            auditor_output,
            table_rows={
                "Sheet1": [[
                    "07/06/2026",
                    "Alex Worker",
                    "100 Main St",
                    "Framing (CC-1)",
                    "08:00",
                    "14:00",
                    6,
                    6,
                    0,
                ]]
            },
        )
        with ZipFile(io.BytesIO(auditor_output.getvalue())) as archive:
            self.assertIsNone(archive.testzip())
            shared = _shared_strings(archive)
            sheet_path = dict(workbook_sheets(archive))["Sheet1"]
            rows = sheet_rows(archive, sheet_path, shared)
            self.assertEqual(rows[1][2], "Alex Worker")
            self.assertEqual(rows[1][3], "100 Main St")

        invoice_output = io.BytesIO()
        fill_template_workbook(
            INVOICE_TEMPLATE,
            invoice_output,
            cell_updates={
                "template": {
                    "F3": "INV-42",
                    "F8": "100 Main St",
                    "A11": "Example Customer",
                    "F16": 125,
                    "G16": 750,
                }
            },
        )
        with ZipFile(io.BytesIO(invoice_output.getvalue())) as archive:
            self.assertIsNone(archive.testzip())
            shared = _shared_strings(archive)
            sheet_path = dict(workbook_sheets(archive))["template"]
            rows = sheet_rows(archive, sheet_path, shared)
            row_by_number = {index + 1: row for index, row in enumerate(rows)}
            self.assertEqual(row_by_number[3][6], "INV-42")
            self.assertEqual(row_by_number[8][6], "100 Main St")
            self.assertEqual(float(row_by_number[16][7]), 750)


if __name__ == "__main__":
    unittest.main()
