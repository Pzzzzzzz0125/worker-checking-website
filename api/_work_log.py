from __future__ import annotations

from collections import defaultdict
from typing import Any

from api._lark_base import number_value, text_value


WORK_LOG_TABLE = "Work Log"
WORK_LOG_KEY_FIELD = "Entry Key"


def compact_number(value: Any) -> str:
    number = round(float(value or 0), 2)
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _safe_text(value: Any) -> str:
    return " ".join(text_value(value).replace("\n", " ").split())


def _location_groups(location_fields: list[dict]) -> list[dict]:
    groups: dict[tuple[int, str, str, str], dict] = {}
    for fields in location_fields:
        name = _safe_text(fields.get("Location"))
        if not name:
            continue
        order = int(number_value(fields.get("Display Order"), 0))
        start = _safe_text(fields.get("Start Time"))
        end = _safe_text(fields.get("End Time"))
        key = (order, name.casefold(), start, end)
        group = groups.setdefault(
            key,
            {
                "name": name,
                "order": order,
                "start": start,
                "end": end,
                "regular": 0.0,
                "overtime": 0.0,
                "hours": 0.0,
                "centers": defaultdict(float),
            },
        )
        regular = number_value(fields.get("Regular Hours"))
        overtime = number_value(fields.get("Overtime Hours"))
        stored_hours = fields.get("Location Hours")
        location_hours = (
            number_value(stored_hours)
            if stored_hours not in (None, "")
            else regular + overtime
        )
        group["regular"] += regular
        group["overtime"] += overtime
        group["hours"] += location_hours
        center_id = _safe_text(fields.get("Cost Center ID"))
        center_name = _safe_text(fields.get("Cost Center Name"))
        if center_id or center_name:
            group["centers"][(center_id, center_name)] += location_hours
    return sorted(
        groups.values(),
        key=lambda item: (item["order"], item["name"].casefold(), item["start"]),
    )


def format_normalized_entry(day: dict, locations: list[dict]) -> str:
    status = _safe_text(day.get("Status")).casefold() or "worked"
    if status == "off":
        original = _safe_text(day.get("Original Text"))
        return original if original.casefold().startswith("off") else "off"
    if status == "sick_leave":
        return "sick leave"
    if status != "worked":
        original = _safe_text(day.get("Original Text"))
        return original or status

    parts = []
    for location in _location_groups(locations):
        regular = round(location["regular"], 2)
        overtime = round(location["overtime"], 2)
        total = round(location["hours"], 2)
        time_text = (
            f"{location['start']}-{location['end']}"
            if location["start"] and location["end"]
            else "time —"
        )
        hours_text = f"{compact_number(total)}h"
        if overtime:
            hours_text += (
                f" ({compact_number(regular)}h reg + "
                f"{compact_number(overtime)}h ot)"
            )
        centers = [
            (
                " ".join(part for part in (center_id, center_name) if part)
                + f" ({compact_number(hours)}h)"
            )
            for (center_id, center_name), hours in sorted(
                location["centers"].items(),
                key=lambda item: (item[0][0].casefold(), item[0][1].casefold()),
            )
        ]
        center_text = " + ".join(centers) if centers else "unassigned"
        parts.append(
            f"{location['name']} [{time_text} | {hours_text} | CC: {center_text}]"
        )

    result = "; ".join(parts)
    if not result:
        result = _safe_text(day.get("Original Text")) or "worked [location missing]"
    overtime = number_value(day.get("Overtime Hours"))
    extra = number_value(day.get("Extra Pay"))
    if overtime:
        result += f", ot {compact_number(overtime)}h"
    if extra:
        result += f", ex ${compact_number(extra)}"
    return result


def work_log_row(day: dict, locations: list[dict]) -> dict:
    day_key = _safe_text(day.get("Work Day Key"))
    grouped = _location_groups(locations)
    overtime = round(number_value(day.get("Overtime Hours")), 2)
    total = round(number_value(day.get("Total Hours")), 2)
    location_total = round(number_value(day.get("Location Hours Sum"), total), 2)
    location_names = []
    centers: set[tuple[str, str]] = set()
    for location in grouped:
        if location["name"] not in location_names:
            location_names.append(location["name"])
        centers.update(location["centers"])
    return {
        WORK_LOG_KEY_FIELD: day_key,
        "Work Date": day.get("Work Date"),
        "Worker Key": _safe_text(day.get("Worker Key")),
        "Worker Name": _safe_text(day.get("Worker Name")),
        "Status": _safe_text(day.get("Status")) or "worked",
        "Normalized Entry": format_normalized_entry(day, locations),
        "Total Hours": total,
        "Location Hours Sum": location_total,
        "Hours Difference": round(
            number_value(day.get("Hours Difference"), total - location_total),
            2,
        ),
        "Regular Hours": round(max(total - overtime, 0), 2),
        "Overtime Hours": overtime,
        "Calculated Overtime Hours": round(
            number_value(day.get("Calculated Overtime Hours"), max(total - 8, 0)),
            2,
        ),
        "Override Reason": _safe_text(day.get("Override Reason")),
        "Override By": _safe_text(day.get("Override By")),
        "Extra Pay": round(number_value(day.get("Extra Pay")), 2),
        "Locations": "; ".join(location_names),
        "Cost Centers": "; ".join(
            " ".join(part for part in center if part)
            for center in sorted(
                centers,
                key=lambda item: (item[0].casefold(), item[1].casefold()),
            )
        ),
        "Notes": _safe_text(day.get("Notes")),
        "Source": _safe_text(day.get("Source")),
        "Confidence": _safe_text(day.get("Confidence")),
        "Updated At": day.get("Updated At"),
    }
