from __future__ import annotations

import calendar
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

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


def pay_period(month: str, half: str) -> tuple[date, date]:
    year, month_number = (int(part) for part in month.split("-", 1))
    if half == "1":
        return date(year, month_number, 1), date(year, month_number, 15)
    if half != "2":
        raise ValueError("Choose payment period 1–15 or 16–end.")
    return date(year, month_number, 16), date(year, month_number, calendar.monthrange(year, month_number)[1])


def report_period(query: dict, today: date | None = None) -> tuple[date, date]:
    """Validate a flexible report range while keeping a predictable default."""
    current = today or date.today()
    try:
        start = date.fromisoformat(
            query.get("from", [current.replace(day=1).isoformat()])[0]
        )
        end = date.fromisoformat(query.get("to", [current.isoformat()])[0])
    except (TypeError, ValueError, IndexError):
        raise ValueError("Choose valid From and To dates.") from None
    if start > end or (end - start).days > 366:
        raise ValueError("Choose a valid date range of 367 days or fewer.")
    return start, end


def load_report_data(
    base: LarkBase,
    start: date,
    end: date,
    *,
    worker_key: str = "",
    location: str = "",
    check_period_start: date | None = None,
) -> dict:
    if hasattr(base, "table_ids"):
        base.table_ids()
    day_parts = [date_range_filter("Work Date", start.isoformat(), end.isoformat())]
    if worker_key:
        day_parts.append(f"CurrentValue.[Worker Key]={formula_string(worker_key)}")
    day_filter = day_parts[0] if len(day_parts) == 1 else f"AND({','.join(day_parts)})"
    location_parts = list(day_parts)
    if location:
        location_parts.append(f"CurrentValue.[Location]={formula_string(location)}")
    location_filter = (
        location_parts[0]
        if len(location_parts) == 1
        else f"AND({','.join(location_parts)})"
    )
    check_filter = (
        f"CurrentValue.[Period Start]=TODATE({formula_string(check_period_start.isoformat())})"
        if check_period_start else ""
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        workers_future = executor.submit(base.records, "Workers")
        days_future = executor.submit(base.records, "Work Days", filter_formula=day_filter)
        locations_future = executor.submit(
            base.records, "Location Entries", filter_formula=location_filter,
        )
        checks_future = (
            executor.submit(
                base.records, "Payroll Checks", filter_formula=check_filter,
            )
            if check_period_start else None
        )
        worker_records = workers_future.result()
        day_records = days_future.result()
        location_records = locations_future.result()
        check_records = checks_future.result() if checks_future else []

    workers = {}
    for record in worker_records:
        key = text_value(field(record, "Worker Key"))
        active = bool_value(field(record, "Active"), True)
        if key and active:
            workers[key] = {
                "id": int(float(key)) if key.replace(".", "", 1).isdigit() else 0,
                "key": key,
                "name": text_value(field(record, "Name")),
                "worker_type": text_value(field(record, "Worker Type")) or "1099",
                "daily_rate": number_value(field(record, "Daily Rate")),
                "active": True,
            }

    locations_by_day: dict[str, list[dict]] = defaultdict(list)
    for record in location_records:
        day_key = text_value(field(record, "Work Day Key"))
        if not day_key:
            continue
        regular = number_value(field(record, "Regular Hours"))
        overtime = number_value(field(record, "Overtime Hours"))
        stored_location_hours = field(record, "Location Hours")
        location_hours = (
            number_value(stored_location_hours)
            if stored_location_hours not in (None, "")
            else regular + overtime
        )
        center_id = text_value(field(record, "Cost Center ID"))
        center_name = text_value(field(record, "Cost Center Name"))
        locations_by_day[day_key].append(
            {
                "location_id": text_value(field(record, "Location Entry Key")),
                "name": text_value(field(record, "Location")),
                "hours": round(location_hours, 2),
                "regular_hours": regular,
                "overtime_hours": overtime,
                "start_time": text_value(field(record, "Start Time")),
                "end_time": text_value(field(record, "End Time")),
                "cost_centers": (
                    [{"id": center_id, "name": center_name}] if center_id else []
                ),
            }
        )

    days = []
    for record in day_records:
        worker_key = text_value(field(record, "Worker Key"))
        work_date = date_value(field(record, "Work Date"))
        if not worker_key or not work_date or worker_key not in workers:
            continue
        day_key = text_value(field(record, "Work Day Key"))
        locations = locations_by_day.get(day_key, [])
        centers = {}
        for location in locations:
            for center in location["cost_centers"]:
                current = centers.setdefault(center["id"], {**center, "hours": 0.0})
                current["hours"] += float(location["hours"]) / max(len(location["cost_centers"]), 1)
        worker = workers.get(worker_key, {})
        days.append(
            {
                "work_day_id": day_key,
                "worker_id": worker.get("id", 0),
                "worker_key": worker_key,
                "worker_name": worker.get("name", "") or text_value(field(record, "Worker Name")),
                "date": work_date,
                "status": text_value(field(record, "Status")) or "worked",
                "total_hours": number_value(field(record, "Total Hours")),
                "extra_pay": number_value(field(record, "Extra Pay")),
                "start_time": text_value(field(record, "Start Time")),
                "end_time": text_value(field(record, "End Time")),
                "notes": text_value(field(record, "Notes")),
                "locations": locations,
                "cost_centers": [
                    {**center, "hours": round(center["hours"], 2)}
                    for center in centers.values()
                ],
            }
        )

    checks = {}
    for record in check_records:
        worker_key = text_value(field(record, "Worker Key"))
        period_start = date_value(field(record, "Period Start"))
        period_end = date_value(field(record, "Period End"))
        if worker_key and period_start:
            checks[(worker_key, period_start)] = bool_value(field(record, "Checked"))
            if period_end:
                checks[(worker_key, period_start, period_end)] = bool_value(
                    field(record, "Checked")
                )
    return {"workers": workers, "days": days, "checks": checks}


def california_overtime(days: list[dict], worker_key: str, start: date, end: date, worker_type: str) -> dict[str, dict]:
    first_week = start - timedelta(days=start.weekday())
    last_week = end + timedelta(days=6 - end.weekday())
    hours_by_date = {
        date.fromisoformat(item["date"]): max(float(item["total_hours"]), 0.0)
        for item in days
        if item["worker_key"] == worker_key
        and item["status"] == "worked"
        and first_week.isoformat() <= item["date"] <= last_week.isoformat()
    }
    result = {}
    cursor = first_week
    while cursor <= last_week:
        week_dates = [cursor + timedelta(days=offset) for offset in range(7)]
        worked_dates = {day for day in week_dates if hours_by_date.get(day, 0) > 0}
        regular_running = 0.0
        for day in week_dates:
            hours = hours_by_date.get(day, 0.0)
            if not hours:
                continue
            if worker_type != "W2":
                regular, overtime, doubletime = hours, 0.0, 0.0
            elif day.weekday() == 6 and len(worked_dates) == 7:
                regular, overtime, doubletime = 0.0, min(hours, 8.0), max(hours - 8.0, 0.0)
            else:
                regular = min(hours, 8.0)
                overtime = min(max(hours - 8.0, 0.0), 4.0)
                doubletime = max(hours - 12.0, 0.0)
                weekly_excess = max(regular_running + regular - 40.0, 0.0)
                if weekly_excess:
                    regular -= weekly_excess
                    overtime += weekly_excess
                regular_running += regular
            if start <= day <= end:
                result[day.isoformat()] = {
                    "regular_hours": round(regular, 2),
                    "overtime_hours": round(overtime, 2),
                    "doubletime_hours": round(doubletime, 2),
                    "weighted_hours": round(regular + overtime * 1.5 + doubletime * 2, 2),
                }
        cursor += timedelta(days=7)
    return result


def aggregate(days: list[dict], field_name: str) -> list[dict]:
    grouped = {}
    for day in days:
        for item in day[field_name]:
            key = item.get("id") or item.get("name", "").casefold()
            if not key:
                continue
            current = grouped.setdefault(
                key,
                {"id": item.get("id", ""), "name": item.get("name", ""), "hours": 0.0, "dates": set(), "workers": set()},
            )
            current["hours"] += float(item.get("hours") or 0)
            current["dates"].add(day["date"])
            current["workers"].add(day["worker_key"])
    output = []
    for item in grouped.values():
        dates = sorted(item.pop("dates"))
        workers = item.pop("workers")
        item.update(
            {
                "hours": round(item["hours"], 2),
                "days": len(dates),
                "worker_count": len(workers),
                "first_date": dates[0] if dates else None,
                "last_date": dates[-1] if dates else None,
            }
        )
        output.append(item)
    return sorted(output, key=lambda item: (-item["hours"], item["name"].casefold()))
