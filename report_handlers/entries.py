from __future__ import annotations

import calendar
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from api._lark import LarkAPIError
from api._lark_base import (
    LarkBase,
    bool_value,
    date_range_filter,
    date_value,
    field,
    formula_string,
    number_value,
    text_value,
    worker_id,
)
from api._shared import cookie_value, json_response, verify_payload


def date_millis(value: date) -> int:
    return int(
        datetime.combine(value, datetime.min.time(), ZoneInfo("America/Los_Angeles")).timestamp()
        * 1000
    )


def query_action(handler: BaseHTTPRequestHandler) -> str:
    return parse_qs(urlparse(handler.path).query).get("action", [""])[0]


def session(handler: BaseHTTPRequestHandler) -> dict | None:
    return verify_payload(cookie_value(handler, "workforce_session"), 12 * 60 * 60)


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    value = json.loads(handler.rfile.read(length) or b"{}")
    if not isinstance(value, dict):
        raise ValueError("The request body must be an object.")
    return value


def workers(base: LarkBase) -> tuple[list[dict], dict[str, dict]]:
    output = []
    by_key = {}
    for index, record in enumerate(base.records("Workers"), start=1):
        key = text_value(field(record, "Worker Key"))
        name = text_value(field(record, "Name"))
        if not key or not name:
            continue
        item = {
            "id": worker_id(key, index),
            "key": key,
            "name": name,
            "active": bool_value(field(record, "Active"), True),
        }
        output.append(item)
        by_key[key] = item
    output.sort(key=lambda item: item["name"].casefold())
    return output, by_key


def load_range(
    base: LarkBase, start: str, end: str, *, worker_key: str = "",
) -> tuple[list[dict], list[dict]]:
    formula = date_range_filter("Work Date", start, end)
    if worker_key:
        formula = f"AND({formula},CurrentValue.[Worker Key]={formula_string(worker_key)})"
    with ThreadPoolExecutor(max_workers=2) as executor:
        days_future = executor.submit(base.records, "Work Days", filter_formula=formula)
        locations_future = executor.submit(
            base.records, "Location Entries", filter_formula=formula,
        )
        return days_future.result(), locations_future.result()


def joined_days(day_records: list[dict], location_records: list[dict]) -> dict[str, dict]:
    allocations: dict[str, dict[str, dict]] = defaultdict(dict)
    for record in location_records:
        day_key = text_value(field(record, "Work Day Key"))
        location_name = text_value(field(record, "Location"))
        if not day_key or not location_name:
            continue
        location = allocations[day_key].setdefault(
            location_name.casefold(),
            {"name": location_name, "hours": 0.0, "cost_centers": []},
        )
        location["hours"] += number_value(field(record, "Regular Hours")) + number_value(
            field(record, "Overtime Hours")
        )
        center_id = text_value(field(record, "Cost Center ID"))
        if center_id and center_id not in {item["id"] for item in location["cost_centers"]}:
            location["cost_centers"].append(
                {"id": center_id, "name": text_value(field(record, "Cost Center Name"))}
            )

    output = {}
    for record in day_records:
        day_key = text_value(field(record, "Work Day Key"))
        if not day_key:
            continue
        output[day_key] = {
            "day_id": record.get("record_id", ""),
            "worker_key": text_value(field(record, "Worker Key")),
            "worker_name": text_value(field(record, "Worker Name")),
            "work_date": date_value(field(record, "Work Date")),
            "status": text_value(field(record, "Status")) or "worked",
            "total_hours": number_value(field(record, "Total Hours")),
            "overtime_hours": number_value(field(record, "Overtime Hours")),
            "extra_pay": number_value(field(record, "Extra Pay")),
            "start_time": text_value(field(record, "Start Time")),
            "end_time": text_value(field(record, "End Time")),
            "notes": text_value(field(record, "Notes")),
            "locations": [
                {**item, "hours": round(item["hours"], 2)}
                for item in allocations.get(day_key, {}).values()
            ],
        }
    return output


def blank_day(worker: dict, work_date: str) -> dict:
    return {
        "worker_id": worker["id"],
        "worker_name": worker["name"],
        "work_date": work_date,
        "status": "worked",
        "total_hours": 8,
        "overtime_hours": 0,
        "extra_pay": 0,
        "start_time": "08:30",
        "end_time": "16:30",
        "notes": "",
        "locations": [],
    }


def output_day(item: dict, worker: dict, work_date: str) -> dict:
    if not item:
        return blank_day(worker, work_date)
    return {
        **item,
        "worker_id": worker["id"],
        "worker_name": item.get("worker_name") or worker["name"],
        "work_date": work_date,
    }


def normalized_text(status: str, locations: list[dict], total: float, extra: float) -> str:
    if status == "off":
        return "off"
    parts = []
    for location in locations:
        hours = location.get("hours")
        parts.append(f"{location['name']}{f'({hours:g})' if hours is not None else ''}")
    result = ";".join(parts)
    overtime = max(total - 8, 0)
    if overtime:
        result += f", ot {overtime:g}h"
    if extra:
        result += f", ex ${extra:g}"
    return result


def validate_row(raw: dict, worker_map: dict[str, dict], forced_worker: str = "") -> dict:
    key = forced_worker or str(int(raw.get("worker_id") or 0))
    worker = worker_map.get(key)
    if not worker:
        raise ValueError(f"Worker {key or '(blank)'} does not exist.")
    work_date = date.fromisoformat(str(raw.get("date") or raw.get("work_date") or ""))
    status = str(raw.get("status") or "worked").casefold()
    if status not in {"worked", "off"}:
        raise ValueError("Status must be worked or off.")
    total = float(raw.get("total_hours") or 0) if status == "worked" else 0.0
    if total < 0 or total > 24:
        raise ValueError("Hours must be between 0 and 24.")
    locations = raw.get("locations") or []
    if status == "worked" and not locations:
        raise ValueError(f"Add a location for {worker['name']} on {work_date.isoformat()}.")
    cleaned = []
    for location in locations if status == "worked" else []:
        name = str(location.get("name") or "").strip()
        centers = location.get("cost_centers") or []
        if not name:
            continue
        if not centers:
            raise ValueError(f"Choose a cost center for {name}.")
        if any(not str(center.get("id") or "").strip() for center in centers):
            raise ValueError(f"Cost center ID is missing for {name}.")
        hours = location.get("hours")
        hours = None if hours in (None, "") else float(hours)
        cleaned.append({"name": name, "hours": hours, "cost_centers": centers})
    if status == "worked" and not cleaned:
        raise ValueError("Add at least one valid location.")
    specified = [item["hours"] is not None for item in cleaned]
    if specified and any(specified) and not all(specified):
        raise ValueError("Enter hours for every location, or leave all location hours blank.")
    return {
        "worker": worker,
        "date": work_date,
        "status": status,
        "total": total,
        "extra": float(raw.get("extra_pay") or 0) if status == "worked" else 0.0,
        "start": str(raw.get("start_time") or "08:30") if status == "worked" else "",
        "end": str(raw.get("end_time") or "16:30") if status == "worked" else "",
        "notes": str(raw.get("notes") or "").strip(),
        "locations": cleaned,
    }


def save_rows(base: LarkBase, rows: list[dict], worker_map: dict[str, dict]) -> dict:
    if not rows:
        return {"days": 0, "locations": 0}
    parsed = [validate_row(row, worker_map, str(row.get("forced_worker") or "")) for row in rows]
    start = min(item["date"] for item in parsed).isoformat()
    end = max(item["date"] for item in parsed).isoformat()
    existing_days, existing_locations = load_range(base, start, end)
    now = date_millis(date.today())
    day_rows = []
    location_rows = []
    affected_keys = set()
    for item in parsed:
        worker = item["worker"]
        day_key = f"{worker['key']}|{item['date'].isoformat()}"
        affected_keys.add(day_key)
        day_rows.append(
            {
                "Work Day Key": day_key,
                "Worker Key": worker["key"],
                "Worker Name": worker["name"],
                "Work Date": date_millis(item["date"]),
                "Status": item["status"],
                "Total Hours": round(item["total"], 2),
                "Overtime Hours": round(max(item["total"] - 8, 0), 2),
                "Extra Pay": round(item["extra"], 2),
                "Start Time": item["start"],
                "End Time": item["end"],
                "Notes": item["notes"],
                "Original Text": normalized_text(
                    item["status"], item["locations"], item["total"], item["extra"]
                ),
                "Source": "web-entry",
                "Confidence": "high",
                "Updated At": now,
            }
        )
        locations = item["locations"]
        allocated = [
            float(location["hours"])
            if location["hours"] is not None
            else item["total"] / max(len(locations), 1)
            for location in locations
        ]
        for location_index, (location, location_hours) in enumerate(zip(locations, allocated), 1):
            centers = location["cost_centers"]
            regular_total = round(
                location_hours * (min(item["total"], 8) / item["total"] if item["total"] else 0),
                2,
            )
            overtime_total = round(location_hours - regular_total, 2)
            regular_used = 0.0
            overtime_used = 0.0
            for center_index, center in enumerate(centers, 1):
                last_center = center_index == len(centers)
                regular_share = (
                    round(regular_total - regular_used, 2)
                    if last_center else round(regular_total / len(centers), 2)
                )
                overtime_share = (
                    round(overtime_total - overtime_used, 2)
                    if last_center else round(overtime_total / len(centers), 2)
                )
                regular_used += regular_share
                overtime_used += overtime_share
                location_rows.append(
                    {
                        "Location Entry Key": f"{day_key}|{location_index}|{center_index}",
                        "Work Day Key": day_key,
                        "Worker Key": worker["key"],
                        "Work Date": date_millis(item["date"]),
                        "Location": location["name"],
                        "Cost Center ID": str(center.get("id") or "").strip(),
                        "Cost Center Name": str(center.get("name") or "").strip(),
                        "Start Time": item["start"],
                        "End Time": item["end"],
                        "Regular Hours": regular_share,
                        "Overtime Hours": overtime_share,
                        "Display Order": location_index,
                    }
                )
    base.batch_set_by_key(
        "Work Days", "Work Day Key", day_rows, existing_records=existing_days,
    )
    new_location_keys = {row["Location Entry Key"] for row in location_rows}
    base.batch_set_by_key(
        "Location Entries", "Location Entry Key", location_rows,
        existing_records=existing_locations,
    )
    stale = [
        str(record.get("record_id") or "")
        for record in existing_locations
        if text_value(field(record, "Work Day Key")) in affected_keys
        and text_value(field(record, "Location Entry Key")) not in new_location_keys
    ]
    base.delete_record_ids("Location Entries", stale)
    return {"days": len(day_rows), "locations": len(location_rows), "deleted_locations": len(stale)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not session(self):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        try:
            base = LarkBase()
            worker_list, worker_map = workers(base)
            action = query_action(self)
            if action == "day":
                selected_date = date.fromisoformat(query.get("date", [""])[0]).isoformat()
                day_records, location_records = load_range(base, selected_date, selected_date)
                existing = joined_days(day_records, location_records)
                rows = [
                    output_day(existing.get(f"{worker['key']}|{selected_date}", {}), worker, selected_date)
                    for worker in worker_list if worker["active"]
                ]
                json_response(self, {"date": selected_date, "workers": rows})
                return
            if action == "worker_month":
                worker_key = query.get("worker_id", [""])[0]
                month = query.get("month", [""])[0]
                year, month_number = (int(value) for value in month.split("-", 1))
                worker = worker_map.get(worker_key)
                if not worker:
                    raise ValueError("Choose a valid worker.")
                last = calendar.monthrange(year, month_number)[1]
                start = date(year, month_number, 1)
                end = date(year, month_number, last)
                day_records, location_records = load_range(
                    base, start.isoformat(), end.isoformat(), worker_key=worker_key,
                )
                existing = joined_days(day_records, location_records)
                days = []
                for day_number in range(1, last + 1):
                    work_date = date(year, month_number, day_number).isoformat()
                    days.append(output_day(existing.get(f"{worker_key}|{work_date}", {}), worker, work_date))
                json_response(self, {"worker": worker, "month": month, "days": days})
                return
            json_response(self, {"error": "Unknown entry route."}, 404)
        except (ValueError, TypeError) as error:
            json_response(self, {"error": f"Invalid entry request: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)

    def do_POST(self) -> None:
        if not session(self):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            body = read_body(self)
            base = LarkBase()
            worker_list, worker_map = workers(base)
            del worker_list
            action = query_action(self)
            if action == "day":
                selected_date = date.fromisoformat(str(body.get("date") or "")).isoformat()
                rows = [{**row, "date": selected_date} for row in body.get("records") or []]
                json_response(self, {"saved": True, **save_rows(base, rows, worker_map)})
                return
            if action == "worker_days":
                forced_worker = str(int(body.get("worker_id") or 0))
                rows = [{**row, "forced_worker": forced_worker} for row in body.get("records") or []]
                json_response(self, {"saved": True, **save_rows(base, rows, worker_map)})
                return
            if action == "worker_days_copy":
                source_rows = body.get("records") or []
                targets = [str(int(value)) for value in body.get("target_worker_ids") or []]
                if not source_rows or not targets:
                    raise ValueError("Choose days and at least one target worker.")
                rows = [
                    {**row, "forced_worker": target}
                    for target in targets for row in source_rows
                ]
                result = save_rows(base, rows, worker_map)
                json_response(
                    self,
                    {
                        "saved": True,
                        **result,
                        "days": len(source_rows),
                        "target_workers": [worker_map[target]["name"] for target in targets],
                    },
                )
                return
            json_response(self, {"error": "Unknown entry route."}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid entry request: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
