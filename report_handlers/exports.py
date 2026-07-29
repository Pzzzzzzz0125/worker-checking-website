from __future__ import annotations

import io
import json
import re
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path

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


def invoice_values(
    data: dict,
    body: dict,
    start: date,
    end: date,
    worker_keys: list[str] | None = None,
    sites: list[str] | None = None,
) -> dict[str, str | float]:
    worker_keys = worker_keys or []
    sites = sites or []
    try:
        billing_rate = round(float(body.get("billing_rate") or 0), 2)
    except (TypeError, ValueError):
        raise ValueError("Billing rate must be a number.") from None
    if billing_rate <= 0 or billing_rate > 1_000_000:
        raise ValueError("Enter a Billing rate greater than 0.")
    bill_to = " ".join(str(body.get("bill_to") or "").split())
    if not bill_to or len(bill_to) > 250:
        raise ValueError("Bill To is required and must be 250 characters or fewer.")
    invoice_date = _date(body.get("invoice_date") or date.today().isoformat(), "Invoice")
    due_date = _date(
        body.get("payment_due")
        or (invoice_date + timedelta(days=30)).isoformat(),
        "Payment Due",
    )
    invoice_number = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        str(body.get("invoice_number") or f"SC-{invoice_date:%Y%m%d}").strip(),
    ).strip("-")[:60]
    if not invoice_number:
        raise ValueError("Invoice number is required.")

    selected_days = _selected_days(data, start, end, worker_keys)
    locations = [
        location
        for day in selected_days
        for location in _selected_locations(day, sites)
        if float(location.get("hours") or 0) > 0
    ]
    if not locations:
        raise ValueError("No worked site hours match the selected filters.")
    hours = round(sum(float(item["hours"]) for item in locations), 2)
    amount = round(hours * billing_rate, 2)
    worker_names = sorted(
        {day["worker_name"] for day in selected_days if _selected_locations(day, sites)},
        key=str.casefold,
    )
    sites = sorted({item["name"] for item in locations}, key=str.casefold)
    worker_label = worker_names[0] if len(worker_names) == 1 else f"{len(worker_names)} workers"
    site_label = sites[0] if len(sites) == 1 else f"{len(sites)} sites"
    description = (
        f"Labor services · {start:%m/%d/%Y}–{end:%m/%d/%Y} · "
        f"{worker_label} · {hours:g} labor hours"
    )
    return {
        "F3": invoice_number,
        "G3": invoice_date.strftime("%m/%d/%Y"),
        "F8": site_label,
        "A11": bill_to,
        "A12": f"Service period: {start:%m/%d/%Y}–{end:%m/%d/%Y}",
        "A13": f"Workers: {', '.join(worker_names)}",
        "A16": description,
        "F16": billing_rate,
        "G16": amount,
        "B27": due_date.strftime("%m/%d/%Y"),
        "G27": amount,
        "G30": amount,
    }


def build_export(base, body: dict) -> tuple[bytes, str]:
    export_type = str(body.get("template") or "").casefold()
    start, end, worker_keys, sites = _filters(body)
    data = _load(base, start, end, worker_keys)
    output = io.BytesIO()
    if export_type == "auditor":
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
        return output.getvalue(), f"Worker-Compensation-Auditor-{start}-{end}.xlsx"
    if export_type == "invoice":
        values = invoice_values(data, body, start, end, worker_keys, sites)
        fill_template_workbook(
            INVOICE_TEMPLATE,
            output,
            cell_updates={"template": values},
        )
        invoice_number = str(values["F3"])
        return output.getvalue(), f"Speed-Invoice-{invoice_number}.xlsx"
    raise ValueError("Choose Worker Compensation Auditor Report or Speed Invoice.")


def _xlsx_response(handler: BaseHTTPRequestHandler, body: bytes, filename: str) -> None:
    handler.send_response(200)
    handler.send_header(
        "Content-Type",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
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
            content, filename = build_export(DataStore(), body)
            _xlsx_response(self, content, filename)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Cannot generate export: {error}"}, 400)
        except FileNotFoundError:
            json_response(self, {"error": "The approved export template is missing."}, 503)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
