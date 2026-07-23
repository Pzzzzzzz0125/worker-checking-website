from __future__ import annotations

from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from io import BytesIO
from zoneinfo import ZoneInfo

from worklog_parser import normalize_name, normalize_space, parse_work_cell
from xlsx_workbook import (
    read_cost_centers,
    read_payroll_workbook,
    read_worker_information,
    read_workbook,
)


def _worker_registry(workbook: dict) -> tuple[list[dict], dict[str, int]]:
    workers: list[dict] = []
    aliases: dict[str, int] = {}
    for sheet in workbook["sheets"]:
        occurrences: Counter[str] = Counter()
        for row in sheet["workers"]:
            normalized = normalize_name(row["name"])
            occurrences[normalized] += 1
            occurrence = occurrences[normalized]
            alias = normalized if occurrence == 1 else f"{normalized}#{occurrence}"
            if alias in aliases:
                continue
            best_index = None
            best_score = 0.0
            if occurrence == 1:
                for index, worker in enumerate(workers):
                    if worker["occurrence"] != 1:
                        continue
                    score = SequenceMatcher(None, normalized, worker["normalized"]).ratio()
                    if score > best_score:
                        best_index, best_score = index, score
            if best_index is not None and best_score >= 0.92:
                aliases[alias] = best_index
                workers[best_index]["aliases"].append(normalize_space(row["name"]))
                continue
            aliases[alias] = len(workers)
            workers.append(
                {
                    "key": str(len(workers) + 1),
                    "name": normalize_space(row["name"]),
                    "normalized": normalized,
                    "occurrence": occurrence,
                    "aliases": [],
                }
            )
    return workers, aliases


def _worker_index(name: str, workers: list[dict], aliases: dict[str, int]) -> int | None:
    normalized = normalize_name(name)
    if normalized in aliases:
        return aliases[normalized]
    scored = sorted(
        (
            (SequenceMatcher(None, normalized, worker["normalized"]).ratio(), index)
            for index, worker in enumerate(workers)
            if worker["occurrence"] == 1
        ),
        reverse=True,
    )
    if not scored or scored[0][0] < 0.88:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return None
    return scored[0][1]


def _date_millis(value: str) -> int:
    timezone = ZoneInfo("America/Los_Angeles")
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone).timestamp() * 1000)


def _split_amount(amount: float, count: int) -> list[float]:
    if count <= 0:
        return []
    base = round(amount / count, 2)
    values = [base] * count
    values[-1] = round(amount - sum(values[:-1]), 2)
    return values


def _location_hours(parsed) -> list[tuple[float, float]]:
    """Return regular/overtime hours while preserving the parsed daily total."""
    count = len(parsed.locations)
    if not count:
        return []
    total = round(parsed.total_hours or 0.0, 2)
    explicit = [item.hours for item in parsed.locations]
    if all(value is None for value in explicit):
        location_totals = _split_amount(total, count)
    else:
        location_totals = [round(value or 0.0, 2) for value in explicit]
        missing = [index for index, value in enumerate(explicit) if value is None]
        remainder = round(max(total - sum(location_totals), 0.0), 2)
        if missing:
            shares = _split_amount(remainder, len(missing))
            for index, share in zip(missing, shares):
                location_totals[index] = share
        elif remainder:
            location_totals[-1] = round(location_totals[-1] + remainder, 2)

    regular_budget = min(total, 8.0)
    result = []
    for location_total in location_totals:
        regular = round(min(location_total, regular_budget), 2)
        overtime = round(max(location_total - regular, 0.0), 2)
        regular_budget = round(max(regular_budget - regular, 0.0), 2)
        result.append((regular, overtime))
    return result


def build_dataset(
    standardized: bytes,
    cost_center_workbook: bytes,
    payroll_workbook: bytes,
    *,
    year: int = 2026,
) -> dict:
    workbook = read_workbook(BytesIO(standardized), year)
    centers = read_cost_centers(BytesIO(cost_center_workbook))
    worker_information = read_worker_information(BytesIO(standardized))
    payroll_rows = read_payroll_workbook(BytesIO(payroll_workbook), year)
    workers, aliases = _worker_registry(workbook)

    latest_sheet = workbook["sheets"][-1] if workbook["sheets"] else {"workers": []}
    active_aliases: set[str] = set()
    occurrences: Counter[str] = Counter()
    for row in latest_sheet["workers"]:
        normalized = normalize_name(row["name"])
        occurrences[normalized] += 1
        occurrence = occurrences[normalized]
        active_aliases.add(normalized if occurrence == 1 else f"{normalized}#{occurrence}")
    active_worker_indexes = {aliases[item] for item in active_aliases if item in aliases}

    for worker in workers:
        worker.update({"worker_type": "1099", "daily_rate": 0.0, "notes": ""})
    for item in worker_information:
        index = _worker_index(item["name"], workers, aliases)
        if index is None:
            continue
        if item.get("daily_rate") is not None:
            workers[index]["daily_rate"] = float(item["daily_rate"])
        notes = [item.get("pay_schedule", ""), item.get("payment_method", ""), item.get("work_status", "")]
        workers[index]["notes"] = " · ".join(value for value in notes if value)
    for item in payroll_rows:
        index = _worker_index(item["name"], workers, aliases)
        if index is None:
            continue
        workers[index]["worker_type"] = item.get("worker_type") or workers[index]["worker_type"]
        if float(item.get("daily_rate") or 0) > 0:
            workers[index]["daily_rate"] = float(item["daily_rate"])

    worker_records = []
    for index, worker in enumerate(workers):
        worker_records.append(
            {
                "Worker Key": worker["key"],
                "Name": worker["name"],
                "Normalized Name": worker["normalized"],
                "Worker Type": worker["worker_type"],
                "Active": index in active_worker_indexes,
                "Daily Rate": round(worker["daily_rate"], 2),
                "Display Order": index + 1,
                "Aliases": "; ".join(worker["aliases"]),
                "Notes": worker["notes"],
            }
        )

    cost_center_records = [
        {
            "Cost Center ID": item["id"],
            "Name": item["name"],
            "Active": True,
            "Display Order": index,
        }
        for index, item in enumerate(centers, start=1)
    ]

    status_counts: Counter[str] = Counter()
    work_day_keys: set[str] = set()
    work_day_records: list[dict] = []
    location_records: list[dict] = []
    total_hours = 0.0
    extra_pay = 0.0
    dates: list[str] = []
    warnings: list[dict] = []
    updated_at = int(datetime.now(tz=ZoneInfo("America/Los_Angeles")).timestamp() * 1000)

    for sheet in workbook["sheets"]:
        occurrences = Counter()
        for row in sheet["workers"]:
            normalized = normalize_name(row["name"])
            occurrences[normalized] += 1
            occurrence = occurrences[normalized]
            alias = normalized if occurrence == 1 else f"{normalized}#{occurrence}"
            worker_index = aliases[alias]
            worker = workers[worker_index]
            for day in row["days"]:
                if not normalize_space(str(day["value"])):
                    continue
                parsed = parse_work_cell(day["value"])
                day_key = f"{worker['key']}|{day['date']}"
                if day_key in work_day_keys:
                    warnings.append(
                        {
                            "worker": worker["name"],
                            "date": day["date"],
                            "source": str(day["value"]),
                            "warning": "Duplicate worker/date; the later row was skipped.",
                        }
                    )
                    continue
                work_day_keys.add(day_key)
                status_counts[parsed.status] += 1
                total = round(parsed.total_hours or 0.0, 2)
                overtime = round(max(total - 8.0, 0.0), 2) if parsed.status == "worked" else 0.0
                work_day_records.append(
                    {
                        "Work Day Key": day_key,
                        "Worker Key": worker["key"],
                        "Worker Name": worker["name"],
                        "Work Date": _date_millis(day["date"]),
                        "Status": parsed.status,
                        "Total Hours": total,
                        "Overtime Hours": overtime,
                        "Extra Pay": parsed.extra_pay,
                        "Start Time": "",
                        "End Time": "",
                        "Notes": parsed.warning or "",
                        "Original Text": str(day["value"]),
                        "Source": "lark-drive-migration",
                        "Confidence": parsed.confidence,
                        "Updated At": updated_at,
                    }
                )
                for location_index, (location, hours) in enumerate(
                    zip(parsed.locations, _location_hours(parsed)), start=1
                ):
                    location_records.append(
                        {
                            "Location Entry Key": f"{day_key}|{location_index}",
                            "Work Day Key": day_key,
                            "Worker Key": worker["key"],
                            "Work Date": _date_millis(day["date"]),
                            "Location": location.name,
                            "Cost Center ID": "",
                            "Cost Center Name": "",
                            "Start Time": "",
                            "End Time": "",
                            "Regular Hours": hours[0],
                            "Overtime Hours": hours[1],
                            "Display Order": location_index,
                        }
                    )
                total_hours += total
                extra_pay += parsed.extra_pay
                dates.append(day["date"])
                if parsed.warning:
                    warnings.append(
                        {
                            "worker": worker["name"],
                            "date": day["date"],
                            "source": str(day["value"]),
                            "warning": parsed.warning,
                        }
                    )

    duplicate_center_ids = len(centers) - len({item["id"] for item in centers})
    preview = {
        "mode": "preview_only",
        "safe_to_write": (
            not duplicate_center_ids
            and bool(workbook["sheets"])
            and bool(payroll_rows)
        ),
        "year": year,
        "date_range": {"start": min(dates, default=""), "end": max(dates, default="")},
        "counts": {
            "sheets": len(workbook["sheets"]),
            "workers": len(worker_records),
            "active_workers": len(active_worker_indexes),
            "work_days": len(work_day_records),
            "worked_days": status_counts["worked"],
            "off_days": status_counts["off"],
            "unknown_days": status_counts["unknown"],
            "location_entries": len(location_records),
            "cost_centers": len(cost_center_records),
            "worker_information_rows": len(worker_information),
            "payroll_reference_rows": len(payroll_rows),
            "warnings": len(warnings),
        },
        "totals": {"hours": round(total_hours, 2), "extra_pay": round(extra_pay, 2)},
        "checks": {
            "workbook_has_period_sheets": bool(workbook["sheets"]),
            "cost_center_ids_unique": duplicate_center_ids == 0,
            "payroll_reference_readable": bool(payroll_rows),
            "historical_cost_centers_will_remain_blank": True,
        },
        "warning_examples": warnings[:20],
    }
    return {
        "preview": preview,
        "tables": {
            "Workers": worker_records,
            "Cost Centers": cost_center_records,
            "Work Days": work_day_records,
            "Location Entries": location_records,
        },
    }


def build_preview(
    standardized: bytes,
    cost_center_workbook: bytes,
    payroll_workbook: bytes,
    *,
    year: int = 2026,
) -> dict:
    return build_dataset(
        standardized,
        cost_center_workbook,
        payroll_workbook,
        year=year,
    )["preview"]
