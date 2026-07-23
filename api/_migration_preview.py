from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from io import BytesIO

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


def build_preview(
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

    status_counts: Counter[str] = Counter()
    work_day_keys: set[str] = set()
    location_count = 0
    total_hours = 0.0
    extra_pay = 0.0
    dates: list[str] = []
    warnings: list[dict] = []

    for sheet in workbook["sheets"]:
        occurrences = Counter()
        for row in sheet["workers"]:
            normalized = normalize_name(row["name"])
            occurrences[normalized] += 1
            occurrence = occurrences[normalized]
            alias = normalized if occurrence == 1 else f"{normalized}#{occurrence}"
            worker_index = aliases[alias]
            worker_key = workers[worker_index]["key"]
            for day in row["days"]:
                if not normalize_space(str(day["value"])):
                    continue
                parsed = parse_work_cell(day["value"])
                key = f"{worker_key}|{day['date']}"
                if key in work_day_keys:
                    warnings.append(
                        {
                            "worker": workers[worker_index]["name"],
                            "date": day["date"],
                            "source": str(day["value"]),
                            "warning": "Duplicate worker/date; the later row would replace the earlier row.",
                        }
                    )
                    continue
                work_day_keys.add(key)
                status_counts[parsed.status] += 1
                location_count += len(parsed.locations)
                total_hours += parsed.total_hours or 0.0
                extra_pay += parsed.extra_pay
                dates.append(day["date"])
                if parsed.warning:
                    warnings.append(
                        {
                            "worker": workers[worker_index]["name"],
                            "date": day["date"],
                            "source": str(day["value"]),
                            "warning": parsed.warning,
                        }
                    )

    duplicate_center_ids = len(centers) - len({item["id"] for item in centers})
    return {
        "mode": "preview_only",
        "safe_to_write": not duplicate_center_ids and bool(workbook["sheets"]),
        "year": year,
        "date_range": {
            "start": min(dates, default=""),
            "end": max(dates, default=""),
        },
        "counts": {
            "sheets": len(workbook["sheets"]),
            "workers": len(workers),
            "active_workers": len(active_worker_indexes),
            "work_days": len(work_day_keys),
            "worked_days": status_counts["worked"],
            "off_days": status_counts["off"],
            "unknown_days": status_counts["unknown"],
            "location_entries": location_count,
            "cost_centers": len(centers),
            "worker_information_rows": len(worker_information),
            "payroll_reference_rows": len(payroll_rows),
            "warnings": len(warnings),
        },
        "totals": {
            "hours": round(total_hours, 2),
            "extra_pay": round(extra_pay, 2),
        },
        "checks": {
            "workbook_has_period_sheets": bool(workbook["sheets"]),
            "cost_center_ids_unique": duplicate_center_ids == 0,
            "payroll_reference_readable": bool(payroll_rows),
            "historical_cost_centers_will_remain_blank": True,
        },
        "warning_examples": warnings[:20],
    }
