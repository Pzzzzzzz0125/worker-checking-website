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
from api._permissions import require_role
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
        by_key[key] = item
        if item["active"]:
            output.append(item)
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
            {
                "name": location_name,
                "hours": 0.0,
                "start_time": text_value(field(record, "Start Time")),
                "end_time": text_value(field(record, "End Time")),
                "cost_centers": [],
            },
        )
        stored_location_hours = field(record, "Location Hours")
        location["hours"] += (
            number_value(stored_location_hours)
            if stored_location_hours not in (None, "")
            else number_value(field(record, "Regular Hours"))
            + number_value(field(record, "Overtime Hours"))
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
        source = text_value(field(record, "Source"))
        location_items = []
        for item in allocations.get(day_key, {}).values():
            location_items.append(
                {
                    **item,
                    "hours": round(item["hours"], 2),
                    # The original spreadsheet migration did not contain time
                    # ranges; its 08:30–16:30 values were placeholders.
                    "start_time": "" if source == "lark-drive-migration" else item["start_time"],
                    "end_time": "" if source == "lark-drive-migration" else item["end_time"],
                }
            )
        stored_location_total = field(record, "Location Hours Sum")
        location_total = (
            number_value(stored_location_total)
            if stored_location_total not in (None, "")
            else round(sum(float(item["hours"]) for item in location_items), 2)
        )
        total_hours = number_value(field(record, "Total Hours"))
        stored_calculated_overtime = field(record, "Calculated Overtime Hours")
        output[day_key] = {
            "day_id": record.get("record_id", ""),
            "worker_key": text_value(field(record, "Worker Key")),
            "worker_name": text_value(field(record, "Worker Name")),
            "work_date": date_value(field(record, "Work Date")),
            "status": text_value(field(record, "Status")) or "worked",
            "total_hours": total_hours,
            "location_hours_sum": location_total,
            "total_hours_source": text_value(field(record, "Total Hours Source")),
            "hours_difference": number_value(
                field(record, "Hours Difference"),
                total_hours - location_total,
            ),
            "overtime_hours": number_value(field(record, "Overtime Hours")),
            "calculated_overtime_hours": number_value(
                stored_calculated_overtime,
                max(total_hours - 8, 0),
            ),
            "overtime_source": text_value(field(record, "Overtime Source")),
            "override_reason": text_value(field(record, "Override Reason")),
            "override_by": text_value(field(record, "Override By")),
            "extra_pay": number_value(field(record, "Extra Pay")),
            "start_time": text_value(field(record, "Start Time")),
            "end_time": text_value(field(record, "End Time")),
            "notes": text_value(field(record, "Notes")),
            "locations": location_items,
        }
    return output


def blank_day(worker: dict, work_date: str) -> dict:
    return {
        "worker_id": worker["id"],
        "worker_name": worker["name"],
        "work_date": work_date,
        "status": "worked",
        "total_hours": 8,
        "location_hours_sum": 8,
        "total_hours_source": "calculated",
        "hours_difference": 0,
        "overtime_hours": 0,
        "calculated_overtime_hours": 0,
        "overtime_source": "calculated",
        "override_reason": "",
        "override_by": "",
        "extra_pay": 0,
        "start_time": "",
        "end_time": "",
        "notes": "",
        "locations": [],
    }


def output_day(item: dict, worker: dict, work_date: str) -> dict:
    if not item:
        return blank_day(worker, work_date)
    return {
        **item,
        "worker_id": worker["id"],
        "worker_name": worker["name"] or item.get("worker_name"),
        "work_date": work_date,
    }


def normalized_text(
    status: str,
    locations: list[dict],
    overtime: float,
    extra: float,
) -> str:
    if status == "off":
        return "off"
    parts = []
    for location in locations:
        hours = location.get("hours")
        parts.append(f"{location['name']}{f'({hours:g})' if hours is not None else ''}")
    result = ";".join(parts)
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
    if not worker["active"]:
        raise ValueError(f"{worker['name']} is archived. Restore the worker before saving entries.")
    work_date = date.fromisoformat(str(raw.get("date") or raw.get("work_date") or ""))
    status = str(raw.get("status") or "worked").casefold()
    if status not in {"worked", "off"}:
        raise ValueError("Status must be worked or off.")
    locations = raw.get("locations") or []
    if status == "worked" and not locations:
        raise ValueError(f"Add a site for {worker['name']} on {work_date.isoformat()}.")
    cleaned = []
    for location in locations if status == "worked" else []:
        name = str(location.get("name") or "").strip()
        centers = location.get("cost_centers") or []
        if not name:
            continue
        if not centers:
            raise ValueError(f"Choose a cost code for {name}.")
        if any(not str(center.get("id") or "").strip() for center in centers):
            raise ValueError(f"Cost code ID is missing for {name}.")
        start_time = str(location.get("start_time") or "")
        end_time = str(location.get("end_time") or "")
        hours = location.get("hours")
        hours = None if hours in (None, "") else float(hours)
        if hours is not None and (hours < 0 or hours > 24):
            raise ValueError(f"Site hours for {name} must be between 0 and 24.")
        cleaned.append(
            {
                "name": name,
                "hours": hours,
                "start_time": start_time,
                "end_time": end_time,
                "cost_centers": centers,
            }
        )
    if status == "worked" and not cleaned:
        raise ValueError("Add at least one valid site.")
    entered_times = [bool(item["start_time"] or item["end_time"]) for item in cleaned]
    calculated_total = None
    if any(entered_times):
        if not all(entered_times) or any(not item["start_time"] or not item["end_time"] for item in cleaned):
            raise ValueError(
                "Time conflict: enter both Start and End for every site, or leave all site times blank."
            )
        ranges = []
        for location in cleaned:
            try:
                start_hour, start_minute = (int(value) for value in location["start_time"].split(":"))
                end_hour, end_minute = (int(value) for value in location["end_time"].split(":"))
            except (ValueError, TypeError):
                raise ValueError(f"Time conflict: invalid time for {location['name']}.")
            start_minutes = start_hour * 60 + start_minute
            end_minutes = end_hour * 60 + end_minute
            if end_minutes <= start_minutes:
                raise ValueError(f"Time conflict: {location['name']} must end after it starts.")
            range_hours = round((end_minutes - start_minutes) / 60, 2)
            if location["hours"] is not None and abs(location["hours"] - range_hours) > 0.01:
                raise ValueError(
                    f"Time conflict: {location['name']}'s time range is "
                    f"{range_hours:g}h, but Site hours is {location['hours']:g}h."
                )
            location["hours"] = range_hours
            ranges.append((start_minutes, end_minutes, location["name"]))
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1]:
                raise ValueError(f"Time conflict: {previous[2]} overlaps {current[2]}.")
    if cleaned and all(item["hours"] is not None for item in cleaned):
        calculated_total = round(sum(float(item["hours"]) for item in cleaned), 2)
    supplied_total = raw.get("total_hours")
    total_source = str(raw.get("total_hours_source") or "calculated").casefold()
    if total_source not in {"calculated", "manual"}:
        raise ValueError("Total hours source must be calculated or manual.")
    if status != "worked":
        total = 0.0
        total_source = "calculated"
    elif total_source == "calculated" and calculated_total is not None:
        # The backend repeats the source-of-truth calculation so a stale
        # browser total cannot overwrite newly edited location hours.
        total = calculated_total
    elif supplied_total in (None, ""):
        total = calculated_total if calculated_total is not None else 8.0
    else:
        total = float(supplied_total)
    if total < 0 or total > 24:
        raise ValueError("Hours must be between 0 and 24.")
    location_total = calculated_total if calculated_total is not None else total
    hours_difference = round(total - location_total, 2)
    override_reason = str(raw.get("override_reason") or "").strip()
    expected_overtime = round(max(total - 8, 0), 2)
    overtime_source = str(raw.get("overtime_source") or "calculated").casefold()
    if overtime_source not in {"calculated", "manual"}:
        raise ValueError("Overtime source must be calculated or manual.")
    if status != "worked":
        overtime = 0.0
        overtime_source = "calculated"
    elif overtime_source == "calculated":
        overtime = expected_overtime
    else:
        overtime = float(raw.get("overtime_hours") or 0)
    if overtime < 0 or overtime > total:
        raise ValueError("Overtime must be between 0 and Total hours.")
    overtime_difference = round(overtime - expected_overtime, 2)
    if (
        (total_source == "manual" and abs(hours_difference) > 0.01)
        or (overtime_source == "manual" and abs(overtime_difference) > 0.01)
    ) and not override_reason:
        raise ValueError(
            "Enter an override reason before saving mismatched Total or Overtime hours."
        )
    return {
        "worker": worker,
        "date": work_date,
        "status": status,
        "total": total,
        "location_total": location_total,
        "total_source": total_source,
        "hours_difference": hours_difference,
        "overtime": overtime,
        "calculated_overtime": expected_overtime,
        "overtime_source": overtime_source,
        "override_reason": override_reason,
        "override_by": str(raw.get("override_by") or "").strip(),
        "extra": float(raw.get("extra_pay") or 0) if status == "worked" else 0.0,
        "start": "",
        "end": "",
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
    now = int(datetime.now(ZoneInfo("America/Los_Angeles")).timestamp() * 1000)
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
                "Location Hours Sum": round(item["location_total"], 2),
                "Total Hours Source": item["total_source"],
                "Hours Difference": round(item["hours_difference"], 2),
                "Overtime Hours": round(item["overtime"], 2),
                "Calculated Overtime Hours": round(item["calculated_overtime"], 2),
                "Overtime Source": item["overtime_source"],
                "Override Reason": item["override_reason"],
                "Override By": item["override_by"] if item["override_reason"] else "",
                "Extra Pay": round(item["extra"], 2),
                "Start Time": item["start"],
                "End Time": item["end"],
                "Notes": item["notes"],
                "Original Text": normalized_text(
                    item["status"], item["locations"], item["overtime"], item["extra"]
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
        regular_remaining = min(item["total"], 8)
        overtime_remaining = item["overtime"]
        for location_index, (location, location_hours) in enumerate(zip(locations, allocated), 1):
            centers = location["cost_centers"]
            regular_total = round(min(location_hours, regular_remaining), 2)
            regular_remaining = round(max(regular_remaining - regular_total, 0), 2)
            overtime_total = round(min(max(location_hours - regular_total, 0), overtime_remaining), 2)
            overtime_remaining = round(max(overtime_remaining - overtime_total, 0), 2)
            regular_used = 0.0
            overtime_used = 0.0
            location_hours_used = 0.0
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
                location_hours_share = (
                    round(location_hours - location_hours_used, 2)
                    if last_center else round(location_hours / len(centers), 2)
                )
                regular_used += regular_share
                overtime_used += overtime_share
                location_hours_used += location_hours_share
                location_rows.append(
                    {
                        "Location Entry Key": f"{day_key}|{location_index}|{center_index}",
                        "Work Day Key": day_key,
                        "Worker Key": worker["key"],
                        "Work Date": date_millis(item["date"]),
                        "Location": location["name"],
                        "Cost Center ID": str(center.get("id") or "").strip(),
                        "Cost Center Name": str(center.get("name") or "").strip(),
                        "Start Time": location["start_time"],
                        "End Time": location["end_time"],
                        "Location Hours": location_hours_share,
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


def clear_day(base: LarkBase, worker_key: str, work_date: str) -> dict:
    selected_date = date.fromisoformat(work_date).isoformat()
    day_key = f"{worker_key}|{selected_date}"
    day_records, location_records = load_range(
        base, selected_date, selected_date, worker_key=worker_key,
    )
    location_ids = [
        str(record.get("record_id") or "")
        for record in location_records
        if text_value(field(record, "Work Day Key")) == day_key
    ]
    day_ids = [
        str(record.get("record_id") or "")
        for record in day_records
        if text_value(field(record, "Work Day Key")) == day_key
    ]
    deleted_locations = base.delete_record_ids("Location Entries", location_ids)
    deleted_days = base.delete_record_ids("Work Days", day_ids)
    return {
        "cleared": True,
        "deleted_days": deleted_days,
        "deleted_locations": deleted_locations,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not session(self):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        try:
            base = DataStore()
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
                if not worker or not worker["active"]:
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
        current_session = session(self)
        if not current_session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        if not require_role(self, current_session, "entry_user"):
            return
        try:
            body = read_body(self)
            actor = str(
                current_session.get("name")
                or current_session.get("sub")
                or ""
            ).strip()
            base = DataStore()
            worker_list, worker_map = workers(base)
            del worker_list
            action = query_action(self)
            if action == "day":
                selected_date = date.fromisoformat(str(body.get("date") or "")).isoformat()
                rows = [
                    {**row, "date": selected_date, "override_by": actor}
                    for row in body.get("records") or []
                ]
                json_response(self, {"saved": True, **save_rows(base, rows, worker_map)})
                return
            if action == "worker_days":
                forced_worker = str(int(body.get("worker_id") or 0))
                rows = [
                    {**row, "forced_worker": forced_worker, "override_by": actor}
                    for row in body.get("records") or []
                ]
                json_response(self, {"saved": True, **save_rows(base, rows, worker_map)})
                return
            if action == "day_clear":
                worker_key = str(int(body.get("worker_id") or 0))
                if worker_key not in worker_map or not worker_map[worker_key]["active"]:
                    raise ValueError("Choose a valid worker.")
                json_response(
                    self,
                    clear_day(base, worker_key, str(body.get("date") or "")),
                )
                return
            if action == "worker_days_copy":
                source_rows = body.get("records") or []
                targets = [str(int(value)) for value in body.get("target_worker_ids") or []]
                if not source_rows or not targets:
                    raise ValueError("Choose days and at least one target worker.")
                if any(target not in worker_map or not worker_map[target]["active"] for target in targets):
                    raise ValueError("Copy targets must be active workers.")
                rows = [
                    {**row, "forced_worker": target, "override_by": actor}
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
