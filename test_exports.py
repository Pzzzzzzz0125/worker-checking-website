import io
import unittest
from datetime import date
from zipfile import ZipFile

from report_handlers.exports import (
    AUDITOR_TEMPLATE,
    INVOICE_TEMPLATE,
    _filters,
    _invoice_pdf,
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
        self.assertAlmostEqual(sum(float(row[8]) for row in rows), 11)

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

    def test_invoice_maps_user_sections_to_the_approved_template(self):
        values = invoice_values({
            "bill_to_name": "Example Customer",
            "bill_to_address": "500 Market St, San Jose, CA 95113",
            "bill_to_phone": "408-555-0100",
            "bill_to_email": "billing@example.com",
            "job_address": "100 Main St",
            "job_address_detail": "San Jose, CA 95112",
            "description": "First progress payment",
            "invoice_number": "INV-42",
            "invoice_date": "2026-07-07",
            "payment_terms": "Upon Receipt",
            "unit_price": 750,
            "amount": 750,
        })
        self.assertEqual(values["F3"], "INV-42")
        self.assertEqual(values["F8"], "100 Main St")
        self.assertEqual(values["F9"], "San Jose, CA 95112")
        self.assertEqual(values["A11"], "Example Customer")
        self.assertEqual(values["A12"], "500 Market St, San Jose, CA 95113")
        self.assertEqual(values["A16"], "First progress payment")
        self.assertEqual(values["F16"], 750)
        self.assertEqual(values["G16"], 750)
        self.assertEqual(values["B27"], "Upon Receipt")

    def test_invoice_number_is_generated_when_not_supplied(self):
        values = invoice_values({
            "bill_to_name": "Example Customer",
            "bill_to_address": "500 Market St",
            "job_address": "100 Main St",
            "description": "Deposit",
            "invoice_date": "2026-07-07",
            "unit_price": 100,
            "amount": 100,
        })
        self.assertRegex(str(values["F3"]), r"^SC-\d{8}-\d{6}$")

    def test_invoice_pdf_is_a_valid_named_pdf(self):
        values = invoice_values({
            "bill_to_name": "Example Customer",
            "bill_to_address": "500 Market St, San Jose, CA 95113",
            "bill_to_phone": "408-555-0100",
            "bill_to_email": "billing@example.com",
            "job_address": "100 Main St",
            "job_address_detail": "San Jose, CA 95112",
            "description": "First progress payment",
            "invoice_number": "INV-42",
            "invoice_date": "2026-07-07",
            "payment_terms": "Upon Receipt",
            "unit_price": 750,
            "amount": 750,
        })
        pdf = _invoice_pdf(values)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10_000)

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
