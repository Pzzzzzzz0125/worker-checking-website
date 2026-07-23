from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from api._lark import LarkAPIError
from api._lark_base import LarkBase, bool_value, field, text_value
from api._shared import json_response
from gemini_parser import extract_work_records
from report_handlers.entries import (
    load_range,
    read_body,
    save_rows,
    session,
    workers,
)
from report_handlers.workers import list_workers
from worklog_parser import normalize_name, normalize_space, parse_work_cell


def split_values(value: object) -> list[str]:
    raw = value if isinstance(value, list) else re.split(r"\s*[;|]+\s*", str(value or ""))
    output = []
    seen = set()
    for item in raw:
        if isinstance(item, dict):
            cleaned = normalize_space(str(item.get("name") or item.get("id") or ""))
        else:
            cleaned = normalize_space(str(item))
        key = cleaned.casefold()
        if cleaned and key not in seen:
            output.append(cleaned)
            seen.add(key)
    return output


def match_worker(profiles: list[dict], source_name: str) -> dict | None:
    normalized = normalize_name(source_name)
    if not normalized:
        return None
    exact = []
    for profile in profiles:
        names = {
            normalize_name(profile["name"]),
            normalize_name(profile.get("normalized_name", "")),
            *(
                normalize_name(alias)
                for alias in str(profile.get("aliases") or "").split(";")
                if alias.strip()
            ),
        }
        if normalized in names:
            exact.append(profile)
    if len(exact) == 1:
        return exact[0]

    candidates = [profile for profile in profiles if profile.get("active")]
    source_tokens = normalized.split()
    if len(source_tokens) == 1:
        first_matches = [
            profile for profile in candidates
            if normalize_name(profile["name"]).split()[:1] == source_tokens
        ]
        if len(first_matches) == 1:
            return first_matches[0]
    scored = []
    for profile in candidates:
        candidate = normalize_name(profile["name"])
        candidate_tokens = candidate.split()
        full_score = SequenceMatcher(None, normalized, candidate).ratio()
        first_score = (
            SequenceMatcher(None, source_tokens[0], candidate_tokens[0]).ratio()
            if source_tokens and candidate_tokens else 0
        )
        overlap = (
            len(set(source_tokens) & set(candidate_tokens)) / len(source_tokens)
            if source_tokens else 0
        )
        score = first_score if len(source_tokens) == 1 else max(full_score, overlap)
        scored.append((score, profile))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < 0.88:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return None
    return scored[0][1]


def cost_centers(base: LarkBase) -> list[dict]:
    output = []
    for record in base.records("Cost Centers"):
        center_id = text_value(field(record, "Cost Center ID"))
        name = text_value(field(record, "Name"))
        if center_id and name and bool_value(field(record, "Active"), True):
            output.append({"id": center_id, "name": name})
    return output


def resolve_centers(centers: list[dict], values: object) -> list[dict]:
    output = []
    seen = set()
    for raw in split_values(values):
        normalized = raw.casefold()
        id_match = re.search(r"(?:·|\()\s*([^·()]+)\)?\s*$", raw)
        possible_id = normalize_space(id_match.group(1)) if id_match else raw
        match = next(
            (
                center for center in centers
                if center["id"].casefold() == possible_id.casefold()
                or center["id"].casefold() == normalized
                or center["name"].casefold() == normalized
                or f"{center['name']} ({center['id']})".casefold() == normalized
            ),
            None,
        )
        if match is None:
            matches = [
                center for center in centers
                if normalized in center["name"].casefold()
                or normalized in center["id"].casefold()
            ]
            match = matches[0] if len(matches) == 1 else None
        if match and match["id"] not in seen:
            output.append(match)
            seen.add(match["id"])
    return output


def normalize_records(
    base: LarkBase, raw_records: list[dict], selected_year: int,
) -> list[dict]:
    profiles = list_workers(base)
    centers = cost_centers(base)
    valid_dates = []
    for raw in raw_records:
        try:
            valid_dates.append(date.fromisoformat(normalize_space(str(raw.get("date") or ""))))
        except ValueError:
            pass
    existing_keys = set()
    if valid_dates:
        days, _ = load_range(
            base, min(valid_dates).isoformat(), max(valid_dates).isoformat(),
        )
        existing_keys = {
            text_value(field(record, "Work Day Key")) for record in days
        }

    output = []
    for index, raw in enumerate(raw_records, start=1):
        source_worker = normalize_space(str(raw.get("worker_name") or ""))
        worker = match_worker(profiles, source_worker)
        issues = []
        try:
            work_date = date.fromisoformat(normalize_space(str(raw.get("date") or "")))
            date_value = work_date.isoformat()
            if work_date.year != selected_year:
                issues.append(f"Date is outside selected year {selected_year}.")
        except ValueError:
            date_value = normalize_space(str(raw.get("date") or ""))
            issues.append("Date needs correction.")
        if not worker:
            issues.append("Worker name does not match the worker list.")
        status = raw.get("status") if raw.get("status") in {"worked", "off"} else "worked"
        location_values = split_values(raw.get("locations") or [])
        if status == "worked" and not location_values:
            issues.append("Worked record needs a location.")
        regular = max(float(raw.get("regular_hours") or 0), 0)
        overtime = max(float(raw.get("overtime_hours") or 0), 0)
        total = max(float(raw.get("total_hours") or 0), 0)
        if status == "worked":
            regular = regular or 8
            total = total or regular + overtime
            total = max(total, regular + overtime)
        else:
            regular = overtime = total = 0
        supplied_centers = split_values(raw.get("cost_centers") or [])
        resolved = resolve_centers(centers, supplied_centers)
        if status == "worked" and not resolved:
            issues.append("Choose the required cost center.")
        elif len(resolved) != len(supplied_centers):
            issues.append("One or more cost centers need correction.")
        warning = normalize_space(str(raw.get("warning") or ""))
        if warning:
            issues.append(warning)
        confidence = str(raw.get("confidence") or "low")
        blocking = (
            not worker
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value)
            or (status == "worked" and (not location_values or not resolved))
            or (date_value[:4].isdigit() and int(date_value[:4]) != selected_year)
        )
        output.append(
            {
                "review_id": index,
                "worker_id": worker["id"] if worker else None,
                "worker_name": worker["name"] if worker else source_worker,
                "source_worker_name": source_worker,
                "date": date_value,
                "status": status,
                "locations": location_values,
                "regular_hours": round(regular, 2),
                "overtime_hours": round(overtime, 2),
                "total_hours": round(total, 2),
                "extra_pay": round(max(float(raw.get("extra_pay") or 0), 0), 2),
                "start_time": normalize_space(str(raw.get("start_time") or "")),
                "end_time": normalize_space(str(raw.get("end_time") or "")),
                "cost_centers": resolved,
                "cost_center_text": " ; ".join(
                    f"{center['name']} ({center['id']})" for center in resolved
                ) or " ; ".join(supplied_centers),
                "notes": normalize_space(str(raw.get("notes") or "")),
                "confidence": confidence,
                "source_excerpt": normalize_space(str(raw.get("source_excerpt") or "")),
                "issues": issues,
                "existing": bool(
                    worker and f"{worker['worker_key']}|{date_value}" in existing_keys
                ),
                "ready": not blocking,
            }
        )
    return output


def apply_records(base: LarkBase, proposed: list[dict]) -> dict:
    if not proposed:
        raise ValueError("Select at least one AI record to save.")
    if len(proposed) > 500:
        raise ValueError("Save 500 records or fewer at one time.")
    profiles = list_workers(base)
    centers = cost_centers(base)
    _, worker_map = workers(base)
    rows = []
    seen = set()
    for index, record in enumerate(proposed, start=1):
        worker = match_worker(profiles, str(record.get("worker_name") or ""))
        if not worker:
            raise ValueError(f"Row {index}: choose a valid worker.")
        work_date = date.fromisoformat(str(record.get("date") or "")).isoformat()
        duplicate = (worker["worker_key"], work_date)
        if duplicate in seen:
            raise ValueError(
                f"Row {index}: {worker['name']} already has a selected record for {work_date}."
            )
        seen.add(duplicate)
        status = str(record.get("status") or "worked").casefold()
        if status not in {"worked", "off"}:
            raise ValueError(f"Row {index}: choose Worked or Off.")
        parsed = parse_work_cell(";".join(split_values(record.get("locations") or []))).to_dict()
        location_items = parsed["locations"]
        resolved = resolve_centers(centers, record.get("cost_centers") or [])
        if status == "worked" and not location_items:
            raise ValueError(f"Row {index}: enter at least one location.")
        if status == "worked" and not resolved:
            raise ValueError(f"Row {index}: choose at least one valid cost center.")
        start_time = str(record.get("start_time") or "")
        end_time = str(record.get("end_time") or "")
        locations = []
        for location in location_items if status == "worked" else []:
            locations.append(
                {
                    "name": location["name"],
                    "hours": location.get("hours"),
                    "start_time": start_time if len(location_items) == 1 else "",
                    "end_time": end_time if len(location_items) == 1 else "",
                    "cost_centers": resolved,
                }
            )
        total = float(record.get("total_hours") or (8 if status == "worked" else 0))
        overtime = float(record.get("overtime_hours") or 0)
        rows.append(
            {
                "worker_id": worker["id"],
                "date": work_date,
                "status": status,
                "total_hours": total,
                "overtime_hours": overtime,
                "extra_pay": float(record.get("extra_pay") or 0),
                "locations": locations,
                "notes": str(record.get("notes") or ""),
            }
        )
    result = save_rows(base, rows, worker_map)
    return {"saved": result["days"], **result}


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if not session(self):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            body = read_body(self)
            action = re.search(r"(?:^|[?&])action=([^&]+)", self.path)
            action_name = action.group(1) if action else ""
            if action_name == "ai_parse":
                if body.get("consent") is not True:
                    raise ValueError(
                        "Confirm that the pasted text will be sent to Google Gemini."
                    )
                source_text = str(body.get("text") or "").strip()
                if not source_text:
                    raise ValueError("Paste work information before analyzing it.")
                if len(source_text) > 50_000:
                    raise ValueError("Use 50,000 characters or fewer.")
                selected_year = int(body.get("year") or date.today().year)
                if not 2020 <= selected_year <= 2100:
                    raise ValueError("Choose a valid year.")
                extracted = extract_work_records(source_text, selected_year, Path("/tmp"))
                base = LarkBase()
                json_response(
                    self,
                    {
                        "model": "Gemini 3.5 Flash",
                        "summary": normalize_space(str(extracted.get("summary") or "")),
                        "warnings": [
                            normalize_space(str(item))
                            for item in extracted.get("warnings", [])
                            if normalize_space(str(item))
                        ],
                        "records": normalize_records(
                            base, extracted.get("records") or [], selected_year,
                        ),
                    },
                )
                return
            if action_name == "ai_apply":
                json_response(
                    self,
                    apply_records(LarkBase(), body.get("records") or []),
                )
                return
            json_response(self, {"error": "Unknown AI route."}, 404)
        except (ValueError, TypeError) as error:
            json_response(self, {"error": f"Invalid AI request: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
