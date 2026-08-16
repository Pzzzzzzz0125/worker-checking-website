from __future__ import annotations

import base64
import binascii
import io
import re
from datetime import date
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._permissions import require_role
from api._lark_base import LarkBase, bool_value, field, text_value
from api._shared import json_response
from gemini_parser import MODEL as GEMINI_MODEL, extract_work_records
from report_handlers.entries import (
    load_range,
    read_body,
    save_rows,
    session,
    workers,
)
from report_handlers.sites import SiteResolver, site_profile
from report_handlers.workers import list_workers
from worklog_parser import normalize_name, normalize_space
from xlsx_workbook import _shared_strings, sheet_rows, workbook_sheets


AI_INLINE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp", "application/pdf", "text/plain", "text/csv"}
AI_XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_AI_FILES = 5
MAX_AI_FILE_BYTES = 2_500_000
MAX_AI_TOTAL_BYTES = 2_500_000


def xlsx_as_row_text(payload: bytes, filename: str) -> str:
    """Preserve spreadsheet row boundaries for the AI association rules."""
    lines = [f"FILE: {filename} (Excel rows)"]
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            shared = _shared_strings(archive)
            for sheet_name, path in workbook_sheets(archive):
                lines.append(f"SHEET: {sheet_name}")
                for row_number, row in enumerate(sheet_rows(archive, path, shared), start=1):
                    values = [normalize_space(str(row[column])) for column in sorted(row) if normalize_space(str(row[column]))]
                    if values:
                        lines.append(f"ROW {row_number}: " + "\t".join(values))
                    if sum(len(line) + 1 for line in lines) >= 45_000:
                        lines.append("[Remaining workbook rows omitted because the AI input limit was reached.]")
                        return "\n".join(lines)
    except (BadZipFile, KeyError, ValueError) as error:
        raise ValueError(f"{filename}: the Excel workbook could not be read ({error}).") from None
    return "\n".join(lines)


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
    return resolve_centers_detailed(centers, values)[0]


def resolve_centers_detailed(
    centers: list[dict], values: object,
) -> tuple[list[dict], list[str]]:
    output = []
    issues = []
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
        if match is None:
            source = normalize_name(raw)
            source_tokens = set(source.split()) - {"labor", "work", "job", "task"}
            ranked = []
            for center in centers:
                candidate = normalize_name(center["name"])
                candidate_tokens = set(candidate.split()) - {"labor", "work", "job", "task"}
                overlap = (
                    len(source_tokens & candidate_tokens) / len(source_tokens)
                    if source_tokens else 0
                )
                similarity = SequenceMatcher(None, source, candidate).ratio()
                ranked.append((max(overlap, similarity), center))
            ranked.sort(key=lambda item: item[0], reverse=True)
            if (
                ranked
                and ranked[0][0] >= 0.72
                and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.12)
            ):
                match = ranked[0][1]
                issues.append(
                    f'Cost Code keyword “{raw}” matched “{match["name"]} ({match["id"]})”; please verify.'
                )
            else:
                issues.append(f'Cost Code keyword “{raw}” did not have one clear match.')
        if match and match["id"] not in seen:
            output.append(match)
            seen.add(match["id"])
    return output, issues


def site_resolver(base: LarkBase) -> tuple[SiteResolver, list[dict]]:
    """Load the read-only Site address directory without mutating it."""
    profiles = [site_profile(record) for record in base.records("Sites")]
    return SiteResolver(profiles), profiles


def parsed_site_values(values: object) -> list[dict]:
    """Parse an optional trailing hour suffix without splitting address commas."""
    output = []
    for raw in split_values(values):
        match = re.search(r"\(\s*(\d+(?:\.\d+)?)\s*(?:h(?:ours?)?)?\s*\)\s*$", raw, re.I)
        name = normalize_space(raw[:match.start()] if match else raw)
        if name:
            output.append({
                "name": name,
                "hours": float(match.group(1)) if match else None,
            })
    return output


def resolve_sites(resolver: SiteResolver, profiles: list[dict], values: object) -> tuple[list[str], list[str]]:
    """Canonicalize shortened Site text and retain any location-hour suffix."""
    output: list[str] = []
    issues: list[str] = []
    seen: set[str] = set()
    for location in parsed_site_values(values):
        source_name = normalize_space(str(location.get("name") or ""))
        match = resolver.resolve(source_name)
        matched_profile = next(
            (item for item in profiles if item.get("site_key") == match.get("site_key")),
            None,
        )
        if not match["matched"]:
            ranked = [
                (
                    SequenceMatcher(
                        None,
                        normalize_name(source_name),
                        normalize_name(
                            item.get("full_address")
                            or item.get("address_line_1")
                            or item.get("name")
                            or ""
                        ),
                    ).ratio(),
                    item,
                )
                for item in profiles
                if item.get("active") and item.get("verified") and item.get("name")
            ]
            ranked.sort(key=lambda pair: pair[0])
            if ranked and ranked[-1][0] >= 0.72:
                _, matched_profile = ranked[-1]
                match = {
                    **match,
                    "matched": True,
                    "name": matched_profile["name"],
                    "site_key": matched_profile["site_key"],
                    "method": "closest_address",
                }
                issues.append(
                    f'“{source_name}” was matched to closest Site “{matched_profile["name"]}”; please verify.'
                )
            else:
                issues.append(f'No Site address match was found for “{source_name}”.')
        canonical = match["name"] if match["matched"] else source_name
        hours = location.get("hours")
        display = f"{canonical}({float(hours):g})" if hours not in (None, "") else canonical
        if display.casefold() not in seen:
            output.append(display)
            seen.add(display.casefold())
    return output, issues


def normalize_records(
    base: LarkBase, raw_records: list[dict], selected_year: int,
) -> list[dict]:
    profiles = list_workers(base)
    centers = cost_centers(base)
    resolver, site_profiles = site_resolver(base)
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
        status = raw.get("status") if raw.get("status") in {"worked", "off", "sick_leave"} else "worked"
        raw_assignments = raw.get("assignments") if isinstance(raw.get("assignments"), list) else []
        if status == "worked" and not raw_assignments:
            raw_assignments = [
                {
                    "site": location,
                    "cost_codes": raw.get("cost_centers") or [],
                    "hours": 0,
                    "start_time": raw.get("start_time") or "",
                    "end_time": raw.get("end_time") or "",
                }
                for location in split_values(raw.get("locations") or [])
            ]
        normalized_assignments = []
        assignment_site_issues = []
        assignment_center_issues = []
        for assignment_index, assignment in enumerate(raw_assignments, start=1):
            if not isinstance(assignment, dict):
                issues.append(f"Work segment {assignment_index} is invalid.")
                continue
            assignment_sites, site_warnings = resolve_sites(
                resolver, site_profiles, [assignment.get("site") or ""],
            )
            supplied_assignment_centers = split_values(assignment.get("cost_codes") or [])
            assignment_centers, center_warnings = resolve_centers_detailed(
                centers, supplied_assignment_centers,
            )
            assignment_site_issues.extend(site_warnings)
            assignment_center_issues.extend(center_warnings)
            normalized_assignments.append({
                "site": assignment_sites[0] if assignment_sites else normalize_space(str(assignment.get("site") or "")),
                "cost_centers": assignment_centers,
                "cost_center_text": " ; ".join(
                    f"{center['name']} ({center['id']})" for center in assignment_centers
                ) or " ; ".join(supplied_assignment_centers),
                "hours": max(float(assignment.get("hours") or 0), 0),
                "start_time": normalize_space(str(assignment.get("start_time") or "")),
                "end_time": normalize_space(str(assignment.get("end_time") or "")),
                "issues": [*site_warnings, *center_warnings],
                "supplied_cost_code_count": len(supplied_assignment_centers),
            })
        issues.extend(assignment_site_issues)
        issues.extend(assignment_center_issues)
        location_values = [item["site"] for item in normalized_assignments if item["site"]]
        if status == "worked" and not location_values:
            issues.append("Worked record needs a site.")
        regular = max(float(raw.get("regular_hours") or 0), 0)
        overtime = max(float(raw.get("overtime_hours") or 0), 0)
        total = max(float(raw.get("total_hours") or 0), 0)
        if status == "worked":
            regular = regular or 8
            total = total or regular + overtime
            total = max(total, regular + overtime)
        elif status == "sick_leave":
            regular = total = 8
            overtime = 0
        else:
            regular = overtime = total = 0
        supplied_centers = split_values(raw.get("cost_centers") or [])
        resolved = []
        resolved_ids = set()
        for assignment in normalized_assignments:
            for center in assignment["cost_centers"]:
                if center["id"] not in resolved_ids:
                    resolved.append(center)
                    resolved_ids.add(center["id"])
        if status == "worked" and not resolved:
            issues.append("Choose the required cost code.")
        warning = normalize_space(str(raw.get("warning") or ""))
        if warning:
            issues.append(warning)
        confidence = str(raw.get("confidence") or "low")
        blocking = (
            not worker
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value)
            or (status == "worked" and (
                not location_values
                or not resolved
                or any(not item["site"] or not item["cost_centers"] for item in normalized_assignments)
                or any(len(item["cost_centers"]) != item["supplied_cost_code_count"] for item in normalized_assignments)
                or any("No Site address match" in issue for issue in assignment_site_issues)
            ))
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
                "assignments": normalized_assignments,
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
    resolver, site_profiles = site_resolver(base)
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
        if status not in {"worked", "off", "sick_leave"}:
            raise ValueError(f"Row {index}: choose Worked, Sick leave, or Off.")
        proposed_assignments = record.get("assignments") if isinstance(record.get("assignments"), list) else []
        if status == "worked" and not proposed_assignments:
            proposed_assignments = [{
                "site": location,
                "cost_codes": record.get("cost_centers") or [],
                "hours": 0,
                "start_time": record.get("start_time") or "",
                "end_time": record.get("end_time") or "",
            } for location in split_values(record.get("locations") or [])]
        locations = []
        for assignment_index, assignment in enumerate(proposed_assignments, start=1):
            if status != "worked":
                break
            if not isinstance(assignment, dict):
                raise ValueError(f"Row {index}, segment {assignment_index}: invalid work segment.")
            canonical_sites, site_issues = resolve_sites(
                resolver, site_profiles, [assignment.get("site") or ""],
            )
            if not canonical_sites or any("No Site address match" in issue for issue in site_issues):
                raise ValueError(f"Row {index}, segment {assignment_index}: choose a Site from the address directory.")
            supplied_centers = split_values(assignment.get("cost_codes") or [])
            resolved, center_issues = resolve_centers_detailed(centers, supplied_centers)
            if not resolved or len(resolved) != len(supplied_centers) or any("did not have one clear match" in issue for issue in center_issues):
                raise ValueError(f"Row {index}, segment {assignment_index}: choose exact Cost Codes.")
            parsed_location = parsed_site_values(canonical_sites)[0]
            locations.append(
                {
                    "name": parsed_location["name"],
                    "hours": float(assignment.get("hours") or parsed_location.get("hours") or 0) or None,
                    "start_time": str(assignment.get("start_time") or ""),
                    "end_time": str(assignment.get("end_time") or ""),
                    "cost_centers": resolved,
                }
            )
        if status == "worked" and not locations:
            raise ValueError(f"Row {index}: enter at least one Site and Cost Code segment.")
        total = float(record.get("total_hours") or (8 if status in {"worked", "sick_leave"} else 0))
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
        current_session = session(self)
        if not current_session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        if not require_role(self, current_session, "entry_user"):
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
                raw_attachments = body.get("attachments") or []
                if not isinstance(raw_attachments, list) or len(raw_attachments) > MAX_AI_FILES:
                    raise ValueError(f"Upload no more than {MAX_AI_FILES} files at once.")
                attachments = []
                total_attachment_bytes = 0
                text_sections = []
                for index, item in enumerate(raw_attachments, start=1):
                    if not isinstance(item, dict):
                        raise ValueError(f"Attachment {index} is invalid.")
                    name = normalize_space(str(item.get("name") or f"attachment-{index}"))[:180]
                    mime_type = str(item.get("mime_type") or "").casefold()
                    if mime_type not in AI_INLINE_TYPES | {AI_XLSX_TYPE}:
                        raise ValueError(
                            f"{name}: use JPG, PNG, WebP, BMP, PDF, XLSX, TXT, or CSV."
                        )
                    encoded = str(item.get("data") or "")
                    try:
                        raw_bytes = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error):
                        raise ValueError(f"{name}: file data is invalid.") from None
                    if not raw_bytes or len(raw_bytes) > MAX_AI_FILE_BYTES:
                        raise ValueError(f"{name}: each file must be 2.5 MB or smaller.")
                    total_attachment_bytes += len(raw_bytes)
                    if total_attachment_bytes > MAX_AI_TOTAL_BYTES:
                        raise ValueError("Uploaded files must total 2.5 MB or less.")
                    if mime_type == AI_XLSX_TYPE:
                        text_sections.append(f"\n\n{xlsx_as_row_text(raw_bytes, name)}")
                    else:
                        attachments.append({
                            "name": name,
                            "mime_type": mime_type,
                            "data": encoded,
                        })
                source_text += "".join(text_sections)
                if not source_text and not attachments:
                    raise ValueError("Paste work information or upload a supported file.")
                if len(source_text) > 50_000:
                    raise ValueError("Use 50,000 characters or fewer.")
                selected_year = int(body.get("year") or date.today().year)
                if not 2020 <= selected_year <= 2100:
                    raise ValueError("Choose a valid year.")
                extracted = extract_work_records(
                    source_text, selected_year, Path("/tmp"), attachments=attachments,
                )
                base = DataStore()
                json_response(
                    self,
                    {
                        "model": GEMINI_MODEL,
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
                    apply_records(DataStore(), body.get("records") or []),
                )
                return
            json_response(self, {"error": "Unknown AI route."}, 404)
        except (ValueError, TypeError) as error:
            json_response(self, {"error": f"Invalid AI request: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
