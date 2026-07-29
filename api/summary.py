from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._lark_base import (
    LarkBase,
    bool_value,
    date_range_filter,
    date_value,
    field,
    formula_string,
    number_value,
    text_value,
)
from api._shared import cookie_value, json_response, verify_payload
from api._reports import california_overtime


def build_summary(base: LarkBase, start: str, end: str, selected_worker: str = "") -> dict:
    requested_start = date.fromisoformat(start)
    requested_end = date.fromisoformat(end)
    query_start = requested_start - timedelta(days=requested_start.weekday())
    query_end = requested_end + timedelta(days=6 - requested_end.weekday())
    filters = [
        date_range_filter(
            "Work Date", query_start.isoformat(), query_end.isoformat(),
        )
    ]
    if selected_worker:
        filters.append(f"CurrentValue.[Worker Key]={formula_string(selected_worker)}")
    record_filter = filters[0] if len(filters) == 1 else f"AND({','.join(filters)})"
    # Overview intentionally reads only Work Days. Location and cost-center
    # allocations belong on their dedicated detail pages and were the largest
    # source of repeated Lark pagination here.
    with ThreadPoolExecutor(max_workers=2) as executor:
        days_future = executor.submit(
            base.records,
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
        workers_future = executor.submit(
            base.records,
            "Workers",
            field_names=("Worker Key", "Worker Type", "Active"),
            cache_seconds=60,
        )
        day_records = days_future.result()
        worker_types = {
            text_value(field(record, "Worker Key")):
                text_value(field(record, "Worker Type")) or "1099"
            for record in workers_future.result()
            if bool_value(field(record, "Active"), True)
        }
        active_worker_keys = set(worker_types)

    records = []
    for record in day_records:
        work_date = date_value(field(record, "Work Date"))
        worker_key = text_value(field(record, "Worker Key"))
        if (
            not work_date
            or worker_key not in active_worker_keys
            or work_date < query_start.isoformat()
            or work_date > query_end.isoformat()
        ):
            continue
        if selected_worker and worker_key != selected_worker:
            continue
        status = text_value(field(record, "Status")) or "worked"
        records.append(
            {
                "id": record.get("record_id", ""),
                "worker_id": int(worker_key) if worker_key.isdigit() else 0,
                "worker_key": worker_key,
                "worker_name": text_value(field(record, "Worker Name")),
                "work_date": work_date,
                "status": status,
                "total_hours": number_value(field(record, "Total Hours")),
                "overtime_hours": number_value(field(record, "Overtime Hours")),
                "extra_pay": number_value(field(record, "Extra Pay")),
            }
        )
    records.sort(key=lambda item: (item["work_date"], item["worker_name"].casefold()), reverse=True)

    selected_records = [
        item for item in records if start <= item["work_date"] <= end
    ]
    worked = [item for item in selected_records if item["status"] == "worked"]
    total_hours = round(sum(item["total_hours"] for item in worked), 2)
    breakdown = {
        worker_key: california_overtime(
            [
                {
                    "worker_key": item["worker_key"],
                    "date": item["work_date"],
                    "status": item["status"],
                    "total_hours": item["total_hours"],
                }
                for item in records
            ],
            worker_key,
            requested_start,
            requested_end,
            worker_type,
        )
        for worker_key, worker_type in worker_types.items()
        if not selected_worker or worker_key == selected_worker
    }
    parts = [
        part for worker_breakdown in breakdown.values()
        for part in worker_breakdown.values()
    ]
    regular_hours = round(sum(item["regular_hours"] for item in parts), 2)
    overtime_hours = round(
        sum(item["overtime_hours"] + item["doubletime_hours"] for item in parts),
        2,
    )
    weighted_hours = round(sum(item["weighted_hours"] for item in parts), 2)
    return {
        "range": {"from": start, "to": end},
        "totals": {
            "hours": total_hours,
            "regular_hours": regular_hours,
            "weighted_hours": weighted_hours,
            "overtime_hours": overtime_hours,
            "active_workers": len({item["worker_id"] for item in worked}),
            "worked_days": len(worked),
            "off_days": len([item for item in selected_records if item["status"] == "off"]),
            "extra_pay": round(sum(item["extra_pay"] for item in worked), 2),
            "average_hours": round(total_hours / len(worked), 2) if worked else 0,
            "last_worked_date": worked[0]["work_date"] if worked else "",
            "record_count": len(selected_records),
        },
        # Overview intentionally contains summaries only. Detailed work history
        # belongs in Payroll Check and Site Check.
        "records": [],
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
            json_response(self, build_summary(DataStore(), start, end, selected_worker))
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
