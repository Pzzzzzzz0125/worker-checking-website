from __future__ import annotations

import io
import json
import re
from html import escape
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from zipfile import ZipFile

from api._data_store import DataStore
from api._lark import LarkAPIError
from api._reports import california_overtime, load_report_data
from api._shared import json_response
from report_handlers.data_access import require_export_access
from xlsx_workbook import fill_template_workbook


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
AUDITOR_TEMPLATE = TEMPLATE_DIR / "Worker Compensation Auditor Report.xlsx"
INVOICE_TEMPLATE = TEMPLATE_DIR / "Speed Invoice Template.xlsx"


def _date(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        raise ValueError(f"Choose a valid {label} date.") from None


def _selection(body: dict, plural: str, singular: str) -> list[str]:
    raw = body.get(plural)
    if raw is None:
        raw = [body.get(singular)] if body.get(singular) not in (None, "") else []
    if not isinstance(raw, list):
        raise ValueError(f"{plural} must be a list.")
    values = []
    for item in raw:
        value = " ".join(str(item or "").split())
        if value and value not in values:
            values.append(value)
    if len(values) > 500:
        raise ValueError(f"Choose no more than 500 {plural.replace('_', ' ')}.")
    return values


def _filters(body: dict) -> tuple[date, date, list[str], list[str]]:
    start = _date(body.get("from"), "From")
    end = _date(body.get("to"), "To")
    if start > end:
        raise ValueError("From date must be on or before To date.")
    if (end - start).days > 366:
        raise ValueError("An export date range cannot exceed 367 days.")
    worker_keys = _selection(body, "worker_ids", "worker_id")
    if any(not worker_key.isdigit() for worker_key in worker_keys):
        raise ValueError("Choose valid workers.")
    sites = _selection(body, "sites", "site")
    if any(len(site) > 250 for site in sites):
        raise ValueError("A site name is too long.")
    return start, end, worker_keys, sites


def _load(base, start: date, end: date, worker_keys: list[str]) -> dict:
    query_start = start - timedelta(days=start.weekday())
    query_end = end + timedelta(days=6 - end.weekday())
    return load_report_data(
        base,
        query_start,
        query_end,
        worker_key=worker_keys[0] if len(worker_keys) == 1 else "",
    )


def _selected_days(
    data: dict,
    start: date,
    end: date,
    worker_keys: list[str],
) -> list[dict]:
    return [
        day
        for day in data["days"]
        if day["status"] == "worked"
        and start.isoformat() <= day["date"] <= end.isoformat()
        and (not worker_keys or day["worker_key"] in worker_keys)
    ]


def _selected_locations(day: dict, sites: list[str]) -> list[dict]:
    if not sites:
        return day["locations"]
    selected_sites = {site.casefold() for site in sites}
    return [
        item
        for item in day["locations"]
        if item["name"].casefold() in selected_sites
    ]


def auditor_rows(
    data: dict,
    start: date,
    end: date,
    worker_keys: list[str] | None = None,
    sites: list[str] | None = None,
) -> list[list[str | float]]:
    worker_keys = worker_keys or []
    sites = sites or []
    breakdowns = {
        key: california_overtime(
            data["days"], key, start, end, worker["worker_type"],
        )
        for key, worker in data["workers"].items()
    }
    dated_rows: list[tuple[str, list[str | float]]] = []
    for day in _selected_days(data, start, end, worker_keys):
        selected = _selected_locations(day, sites)
        if not selected:
            continue
        all_site_hours = sum(
            max(float(item.get("hours") or 0), 0.0)
            for item in day["locations"]
        )
        day_part = breakdowns.get(day["worker_key"], {}).get(
            day["date"],
            {
                "regular_hours": float(day["total_hours"]),
                "overtime_hours": 0.0,
                "doubletime_hours": 0.0,
                "weighted_hours": float(day["total_hours"]),
            },
        )
        for location in selected:
            hours = max(float(location.get("hours") or 0), 0.0)
            if not hours:
                continue
            share = hours / all_site_hours if all_site_hours else 0.0
            regular = round(float(day_part["regular_hours"]) * share, 2)
            weighted = round(float(day_part["weighted_hours"]) * share, 2)
            cost_codes = "; ".join(
                f"{code.get('name') or 'Cost code'} ({code.get('id')})"
                for code in location.get("cost_centers") or []
                if code.get("id")
            ) or "Unassigned"
            dated_rows.append(
                (
                    day["date"],
                    [
                    date.fromisoformat(day["date"]).strftime("%m/%d/%Y"),
                    day["worker_name"],
                    location["name"],
                    cost_codes,
                    location.get("start_time") or "",
                    location.get("end_time") or "",
                    round(hours, 2),
                    regular,
                    weighted,
                    ],
                )
            )
    dated_rows.sort(
        key=lambda item: (
            item[0],
            str(item[1][1]).casefold(),
            str(item[1][2]).casefold(),
        )
    )
    return [row for _, row in dated_rows]


def _invoice_text(
    body: dict, key: str, label: str, *, required: bool = False, limit: int = 250,
) -> str:
    value = " ".join(str(body.get(key) or "").split())
    if required and not value:
        raise ValueError(f"{label} is required.")
    if len(value) > limit:
        raise ValueError(f"{label} must be {limit} characters or fewer.")
    return value


def invoice_values(body: dict) -> dict[str, str | float]:
    try:
        unit_price = round(float(body.get("unit_price") or 0), 2)
        amount = round(float(body.get("amount") or unit_price), 2)
    except (TypeError, ValueError):
        raise ValueError("Unit price and amount must be numbers.") from None
    if unit_price <= 0 or unit_price > 100_000_000:
        raise ValueError("Enter a Unit price greater than 0.")
    if amount <= 0 or amount > 100_000_000:
        raise ValueError("Enter an Amount greater than 0.")

    bill_to_name = _invoice_text(
        body, "bill_to_name", "Bill To name", required=True, limit=120,
    )
    bill_to_address = _invoice_text(
        body, "bill_to_address", "Bill To address", required=True, limit=180,
    )
    bill_to_phone = _invoice_text(body, "bill_to_phone", "Bill To phone", limit=60)
    bill_to_email = _invoice_text(body, "bill_to_email", "Bill To email", limit=120)
    job_address = _invoice_text(
        body, "job_address", "Job address", required=True, limit=180,
    )
    job_address_detail = _invoice_text(
        body, "job_address_detail", "Job address details", limit=180,
    )
    description = _invoice_text(
        body, "description", "Description", required=True, limit=500,
    )
    payment_terms = _invoice_text(
        body, "payment_terms", "Payment terms", limit=80,
    ) or "Upon Receipt"
    invoice_date = _date(body.get("invoice_date") or date.today().isoformat(), "Invoice")
    invoice_number = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        str(body.get("invoice_number") or datetime.now().strftime("SC-%Y%m%d-%H%M%S")).strip(),
    ).strip("-")[:60]
    if not invoice_number:
        raise ValueError("Invoice number is required.")
    contact = " · ".join(
        value for value in (
            f"Tel: {bill_to_phone}" if bill_to_phone else "",
            f"Email: {bill_to_email}" if bill_to_email else "",
        ) if value
    )
    return {
        "F3": invoice_number,
        "G3": invoice_date.strftime("%m/%d/%Y"),
        "F8": job_address,
        "F9": job_address_detail,
        "A11": bill_to_name,
        "A12": bill_to_address,
        "A13": contact,
        "A16": description,
        "F16": unit_price,
        "G16": amount,
        "B27": payment_terms,
        "G27": amount,
        "G30": amount,
    }


def _invoice_pdf(values: dict[str, str | float]) -> bytes:
    """Render a print-ready invoice without relying on Office on Vercel."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    output = io.BytesIO()
    invoice_number = str(values["F3"])
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.4 * inch,
        title=f"Speed Invoice {invoice_number}",
        author="Speed Construction and Development Inc",
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "InvoiceBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.2, leading=12, textColor=colors.HexColor("#111827"),
    )
    small_style = ParagraphStyle(
        "InvoiceSmall", parent=body_style, fontSize=8, leading=10,
    )
    section_style = ParagraphStyle(
        "InvoiceSection", parent=body_style, fontName="Helvetica-Bold",
        fontSize=9.5, leading=11, textColor=colors.HexColor("#17324D"),
    )
    title_style = ParagraphStyle(
        "InvoiceTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=25, leading=28, alignment=TA_RIGHT,
        textColor=colors.HexColor("#17324D"),
    )
    centered_small = ParagraphStyle(
        "InvoiceCenteredSmall", parent=small_style, alignment=TA_CENTER,
    )
    right_total = ParagraphStyle(
        "InvoiceRightTotal", parent=body_style, fontName="Helvetica-Bold",
        alignment=TA_RIGHT,
    )

    def paragraph(value: object, style=body_style, *, trusted: bool = False) -> Paragraph:
        text = str(value or "")
        if not trusted:
            text = escape(text)
        text = text.replace("\n", "<br/>")
        return Paragraph(text or "&nbsp;", style)

    def money(value: object) -> str:
        return f"${float(value or 0):,.2f}"

    with ZipFile(INVOICE_TEMPLATE) as archive:
        logo_data = io.BytesIO(archive.read("xl/media/image1.jpeg"))
    logo = Image(logo_data, width=2.45 * inch, height=0.59 * inch)

    company = Table([
        [logo],
        [paragraph(
            "<b>Speed Construction</b><br/>Lic. #1098660 · Logan Du<br/>"
            "10275 N De Anza Blvd<br/>Cupertino, CA 95014<br/>"
            "Tel: (510) 415-5834 · Email: logan@speedcons.com",
            small_style, trusted=True,
        )],
    ], colWidths=[3.0 * inch])
    company.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
    ]))

    invoice_meta = Table([
        [Paragraph("INVOICE", title_style)],
        [Table([
            [paragraph("<b>INVOICE #</b>", centered_small, trusted=True), paragraph("<b>DATE</b>", centered_small, trusted=True)],
            [paragraph(invoice_number, centered_small), paragraph(values["G3"], centered_small)],
        ], colWidths=[1.35 * inch, 1.35 * inch], style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#475569")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))],
    ], colWidths=[2.7 * inch])
    invoice_meta.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))

    story = [Table([[company, invoice_meta]], colWidths=[3.55 * inch, 3.25 * inch], style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ])), Spacer(1, 12)]

    address_table = Table([
        [paragraph("BILL TO", section_style), paragraph("JOB ADDRESS", section_style)],
        [paragraph(
            f"<b>{escape(str(values['A11']))}</b><br/>"
            f"{escape(str(values['A12']))}<br/>{escape(str(values['A13']))}",
            trusted=True,
        ), paragraph(
            f"<b>{escape(str(values['F8']))}</b><br/>{escape(str(values['F9']))}",
            trusted=True,
        )],
    ], colWidths=[3.35 * inch, 3.45 * inch])
    address_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#94A3B8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
    ]))
    story.extend([address_table, Spacer(1, 15)])

    line_items = Table([
        [paragraph("DESCRIPTION", section_style), paragraph("UNIT PRICE", section_style), paragraph("AMOUNT", section_style)],
        [paragraph(values["A16"]), paragraph(money(values["F16"]), right_total), paragraph(money(values["G16"]), right_total)],
    ], colWidths=[4.45 * inch, 1.15 * inch, 1.2 * inch], rowHeights=[0.28 * inch, 2.25 * inch])
    line_items.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#475569")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ("ALIGN", (1, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
    ]))
    story.append(line_items)

    totals = Table([
        [paragraph("<b>Payment Due:</b>", trusted=True), paragraph(values["B27"]), paragraph("<b>SUB-TOTAL:</b>", right_total, trusted=True), paragraph(money(values["G27"]), right_total)],
        [paragraph("MAKE CHECK PAYABLE TO:", small_style), paragraph("<b>Speed Construction and Development Inc</b>", small_style, trusted=True), paragraph("<b>AMOUNT DUE:</b>", right_total, trusted=True), paragraph(f"<b>{money(values['G30'])}</b>", right_total, trusted=True)],
    ], colWidths=[1.2 * inch, 3.25 * inch, 1.15 * inch, 1.2 * inch])
    totals.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#475569")),
        ("SPAN", (0, 1), (0, 1)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (2, 1), (-1, 1), colors.HexColor("#F1F5F9")),
    ]))
    story.extend([
        totals,
        Spacer(1, 12),
        paragraph("QUESTIONS CONCERNING THIS INVOICE? CALL LOGAN AT 510-415-5834.", centered_small),
        Spacer(1, 3),
        paragraph(
            "Our goal is to serve clients to the best of our ability. If we ever disappoint you, "
            "we hope you let us know; we will do everything we can to make things right. Thank you "
            "again for selecting us. It is our privilege to work with you.",
            centered_small,
        ),
        Spacer(1, 4),
        paragraph("<b>THANK YOU FOR THE OPPORTUNITY TO SERVICE YOUR NEEDS</b>", centered_small, trusted=True),
    ])
    document.build(story)
    return output.getvalue()


def build_export(base, body: dict) -> tuple[bytes, str, str]:
    export_type = str(body.get("template") or "").casefold()
    output = io.BytesIO()
    if export_type == "auditor":
        start, end, worker_keys, sites = _filters(body)
        data = _load(base, start, end, worker_keys)
        rows = auditor_rows(data, start, end, worker_keys, sites)
        if not rows:
            raise ValueError("No worked site hours match the selected filters.")
        fill_template_workbook(
            AUDITOR_TEMPLATE,
            output,
            cell_updates={"Sheet1": {
                "G1": "Actual hours",
                "H1": "Regular hours",
                "I1": "Weighted payroll hours",
            }},
            table_rows={"Sheet1": rows},
        )
        return (
            output.getvalue(),
            f"Worker-Compensation-Auditor-{start}-{end}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if export_type == "invoice":
        values = invoice_values(body)
        export_format = str(body.get("format") or "xlsx").casefold()
        if export_format not in {"xlsx", "pdf"}:
            raise ValueError("Choose Excel or PDF for the invoice format.")
        invoice_number = str(values["F3"])
        if export_format == "pdf":
            return (
                _invoice_pdf(values),
                f"Speed-Invoice-{invoice_number}.pdf",
                "application/pdf",
            )
        fill_template_workbook(
            INVOICE_TEMPLATE,
            output,
            cell_updates={"template": values},
        )
        return (
            output.getvalue(),
            f"Speed-Invoice-{invoice_number}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    raise ValueError("Choose Worker Compensation Auditor Report or Speed Invoice.")


def _file_response(
    handler: BaseHTTPRequestHandler, body: bytes, filename: str, content_type: str,
) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if not require_export_access(self):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            content, filename, content_type = build_export(DataStore(), body)
            _file_response(self, content, filename, content_type)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Cannot generate export: {error}"}, 400)
        except FileNotFoundError:
            json_response(self, {"error": "The approved export template is missing."}, 503)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
