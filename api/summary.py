from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._lark_base import (
    LarkBase,
    date_range_filter,
    date_value,
    field,
    formula_string,
    number_value,
    text_value,
)
from api._shared import cookie_value, json_response, verify_payload


def build_summary(base: LarkBase, start: str, end: str, selected_worker: str = "") -> dict:
    filters = [date_range_filter("Work Date", start, end)]
    if selected_worker:
        filters.append(f"CurrentValue.[Worker Key]={formula_string(selected_worker)}")
    record_filter = filters[0] if len(filters) == 1 else f"AND({','.join(filters)})"
    # Overview intentionally reads only Work Days. Location and cost-center
    # allocations belong on their dedicated detail pages and were the largest
    # source of repeated Lark pagination here.
    day_records = base.records(
        "Work Days",
        filter_formula=record_filter,
        field_names=(
            "Worker Key",
            "Worker Name",
            "Work Date",
            "Status",
            "Total Hours",
            "Overtime Hours",
            "Extra Pay",
        ),
        cache_seconds=120,
    )

    records = []
    for record in day_records:
        work_date = date_value(field(record, "Work Date"))
        worker_key = text_value(field(record, "Worker Key"))
        if not work_date or work_date < start or work_date > end:
            continue
        if selected_worker and worker_key != selected_worker:
            continue
        status = text_value(field(record, "Status")) or "worked"
        records.append(
            {
                "id": record.get("record_id", ""),
                "worker_id": int(worker_key) if worker_key.isdigit() else 0,
                "worker_name": text_value(field(record, "Worker Name")),
                "work_date": work_date,
                "status": status,
                "total_hours": number_value(field(record, "Total Hours")),
                "overtime_hours": number_value(field(record, "Overtime Hours")),
                "extra_pay": number_value(field(record, "Extra Pay")),
            }
        )
    records.sort(key=lambda item: (item["work_date"], item["worker_name"].casefold()), reverse=True)

    worked = [item for item in records if item["status"] == "worked"]
    total_hours = round(sum(item["total_hours"] for item in worked), 2)
    overtime_hours = round(sum(item["overtime_hours"] for item in worked), 2)
    return {
        "range": {"from": start, "to": end},
        "totals": {
            "hours": total_hours,
            "regular_hours": round(max(0, total_hours - overtime_hours), 2),
            "overtime_hours": overtime_hours,
            "active_workers": len({item["worker_id"] for item in worked}),
            "worked_days": len(worked),
            "off_days": len([item for item in records if item["status"] == "off"]),
            "extra_pay": round(sum(item["extra_pay"] for item in worked), 2),
            "average_hours": round(total_hours / len(worked), 2) if worked else 0,
            "last_worked_date": worked[0]["work_date"] if worked else "",
            "record_count": len(records),
        },
        # A compact activity list keeps the page useful without returning and
        # rendering an entire pay-history table.
        "records": records[:50],
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        session = verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        start = query.get("from", [""])[0]
        end = query.get("to", [""])[0]
        if len(start) != 10 or len(end) != 10 or start > end:
            json_response(self, {"error": "Use a valid from/to date range."}, 400)
            return
        selected_worker = query.get("worker_id", [""])[0]
        try:
            json_response(self, build_summary(LarkBase(), start, end, selected_worker))
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
