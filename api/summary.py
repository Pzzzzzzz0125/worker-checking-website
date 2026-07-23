from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._lark_base import LarkBase, date_value, field, number_value, text_value
from api._shared import cookie_value, json_response, verify_payload


def build_summary(base: LarkBase, start: str, end: str, selected_worker: str = "") -> dict:
    # Resolve table metadata once, then overlap the three independent Lark
    # record requests. This changes latency from their sum to roughly the
    # slowest individual request.
    if hasattr(base, "table_ids"):
        base.table_ids()
    with ThreadPoolExecutor(max_workers=3) as executor:
        workers_future = executor.submit(base.records, "Workers")
        allocations_future = executor.submit(base.records, "Location Entries")
        days_future = executor.submit(base.records, "Work Days")
        worker_records = workers_future.result()
        allocation_records = allocations_future.result()
        day_records = days_future.result()

    workers = {
        text_value(field(record, "Worker Key")): text_value(field(record, "Name"))
        for record in worker_records
        if text_value(field(record, "Worker Key"))
    }
    allocations: dict[str, list[dict]] = defaultdict(list)
    for record in allocation_records:
        day_key = text_value(field(record, "Work Day Key"))
        if not day_key:
            continue
        allocations[day_key].append(
            {
                "name": text_value(field(record, "Location")),
                "hours": number_value(field(record, "Regular Hours")),
                "cost_center": {
                    "id": text_value(field(record, "Cost Center ID")),
                    "name": text_value(field(record, "Cost Center Name")),
                },
            }
        )

    records = []
    for record in day_records:
        work_date = date_value(field(record, "Work Date"))
        worker_key = text_value(field(record, "Worker Key"))
        if not work_date or work_date < start or work_date > end:
            continue
        if selected_worker and worker_key != selected_worker:
            continue
        day_key = text_value(field(record, "Work Day Key"))
        day_allocations = allocations.get(day_key, [])
        locations: dict[str, dict] = {}
        centers: dict[str, dict] = {}
        for item in day_allocations:
            location_name = item["name"]
            center = item["cost_center"]
            if location_name:
                location = locations.setdefault(
                    location_name,
                    {"name": location_name, "hours": 0.0, "cost_centers": []},
                )
                location["hours"] += item["hours"]
                if center["id"] and center["id"] not in {x["id"] for x in location["cost_centers"]}:
                    location["cost_centers"].append(center)
            if center["id"]:
                centers[center["id"]] = center
        status = text_value(field(record, "Status")) or "worked"
        records.append(
            {
                "id": record.get("record_id", ""),
                "worker_id": int(worker_key) if worker_key.isdigit() else 0,
                "worker_name": text_value(field(record, "Worker Name")) or workers.get(worker_key, ""),
                "work_date": work_date,
                "status": status,
                "total_hours": number_value(field(record, "Total Hours")),
                "overtime_hours": number_value(field(record, "Overtime Hours")),
                "extra_pay": number_value(field(record, "Extra Pay")),
                "start_time": text_value(field(record, "Start Time")),
                "end_time": text_value(field(record, "End Time")),
                "notes": text_value(field(record, "Notes")),
                "locations": list(locations.values()),
                "cost_centers": list(centers.values()),
            }
        )
    records.sort(key=lambda item: (item["work_date"], item["worker_name"].casefold()), reverse=True)

    worked = [item for item in records if item["status"] == "worked"]
    daily: dict[str, float] = defaultdict(float)
    for item in worked:
        daily[item["work_date"]] += item["total_hours"]
    return {
        "range": {"from": start, "to": end},
        "totals": {
            "hours": round(sum(item["total_hours"] for item in worked), 2),
            "active_workers": len({item["worker_id"] for item in worked}),
            "worked_days": len(worked),
            "off_days": len([item for item in records if item["status"] == "off"]),
            "extra_pay": round(sum(item["extra_pay"] for item in worked), 2),
        },
        "records": records,
        "daily": [
            {"date": work_date, "hours": round(hours, 2)}
            for work_date, hours in sorted(daily.items())
        ],
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
