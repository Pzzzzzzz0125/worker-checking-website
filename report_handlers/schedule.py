from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._data_store import DataStore
from api._lark import LarkAPIError
from api._lark_base import bool_value, field, text_value
from api._permissions import require_role
from api._postgres_base import PostgresBase
from api._shared import cookie_value, json_response, verify_payload


TABLE = "Schedules"
KEY_FIELD = "Schedule Key"
ACTIVE_STATUSES = {"confirmed", "pending_approval"}


def _session(handler: BaseHTTPRequestHandler) -> dict | None:
    return verify_payload(cookie_value(handler, "workforce_session"), 12 * 60 * 60)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _date(value: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        raise ValueError("Choose a valid schedule date.") from None


def _minutes(value: str) -> int | None:
    value = _clean(value, 20)
    if not value:
        return None
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (TypeError, ValueError):
        raise ValueError("Schedule times must use HH:MM format.") from None
    if hour not in range(24) or minute not in range(60):
        raise ValueError("Schedule times must use HH:MM format.")
    return hour * 60 + minute


def _overlap(start_a: int | None, end_a: int | None, start_b: int | None, end_b: int | None) -> bool:
    # A missing range is deliberately treated as potentially overlapping. It
    # must be approved before two different sites can share a worker's day.
    if None in {start_a, end_a, start_b, end_b}:
        return True
    if end_a <= start_a or end_b <= start_b:
        raise ValueError("Schedule end time must be later than its start time.")
    return start_a < end_b and start_b < end_a


def _ready_store():
    base = DataStore()
    if isinstance(base, PostgresBase):
        # This is idempotent and adds the Schedules record collection to an
        # existing PostgreSQL deployment without requiring a manual migration.
        base.ensure_schema()
    elif not base.table_ids().get(TABLE):
        raise LarkAPIError(
            "The Lark Base Schedules table is missing. Run Lark Base setup once as an administrator.",
            status=503,
        )
    return base


def _workers(base) -> dict[str, dict]:
    result = {}
    for record in base.records("Workers", cache_seconds=0):
        key = text_value(field(record, "Worker Key"))
        name = text_value(field(record, "Name"))
        if key and name:
            result[key] = {
                "worker_key": key,
                "worker_name": name,
                "active": bool_value(field(record, "Active"), True),
            }
    return result


def _row(record: dict) -> dict:
    values = record.get("fields") or {}
    return {
        "schedule_key": text_value(values.get("Schedule Key")),
        "worker_key": text_value(values.get("Worker Key")),
        "worker_name": text_value(values.get("Worker Name")),
        "schedule_date": text_value(values.get("Schedule Date")),
        "site": text_value(values.get("Site")),
        "task": text_value(values.get("Task")),
        "start_time": text_value(values.get("Start Time")),
        "end_time": text_value(values.get("End Time")),
        "notes": text_value(values.get("Notes")),
        "status": text_value(values.get("Status")) or "confirmed",
        "conflict_reason": text_value(values.get("Conflict Reason")),
        "submitted_by": text_value(values.get("Submitted By")),
        "submitted_by_name": text_value(values.get("Submitted By Name")),
        "reviewed_by": text_value(values.get("Reviewed By")),
        "reviewed_by_name": text_value(values.get("Reviewed By Name")),
        "reviewed_at": text_value(values.get("Reviewed At")),
        "created_at": text_value(values.get("Created At")),
        "updated_at": text_value(values.get("Updated At")),
        "record_id": str(record.get("record_id") or ""),
    }


def _conflict_reason(candidate: dict, existing: list[dict]) -> str:
    candidate_start = _minutes(candidate["start_time"])
    candidate_end = _minutes(candidate["end_time"])
    reasons = []
    for row in existing:
        if row["schedule_key"] == candidate["schedule_key"]:
            continue
        if row["status"] not in ACTIVE_STATUSES:
            continue
        if row["worker_key"] != candidate["worker_key"] or row["schedule_date"] != candidate["schedule_date"]:
            continue
        if (
            row["site"].casefold() == candidate["site"].casefold()
            and row["task"].casefold() == candidate["task"].casefold()
            and row["start_time"] == candidate["start_time"]
            and row["end_time"] == candidate["end_time"]
        ):
            raise ValueError("This schedule already exists.")
        if row["site"].casefold() != candidate["site"].casefold():
            if _overlap(
                candidate_start,
                candidate_end,
                _minutes(row["start_time"]),
                _minutes(row["end_time"]),
            ):
                reasons.append(
                    f"{candidate['worker_name']} is also scheduled at {row['site']} "
                    f"on {candidate['schedule_date']} ({row['start_time'] or 'time not set'}–{row['end_time'] or 'time not set'})."
                )
    return " ".join(dict.fromkeys(reasons))


def _payload(body: dict, worker: dict, current: dict | None = None) -> dict:
    site = _clean(body.get("site"), 240)
    task = _clean(body.get("task"), 240)
    if not site:
        raise ValueError("Site is required for every schedule.")
    if not task:
        raise ValueError("Work task is required for every schedule.")
    start = _clean(body.get("start_time"), 20)
    end = _clean(body.get("end_time"), 20)
    _minutes(start)
    _minutes(end)
    if bool(start) != bool(end):
        raise ValueError("Enter both a start and end time, or leave both blank.")
    schedule_date = _date(body.get("schedule_date") or body.get("date"))
    return {
        "Schedule Key": (current or {}).get("schedule_key") or _clean(body.get("schedule_key"), 120) or f"SCH-{schedule_date}-{uuid.uuid4().hex[:10]}",
        "Worker Key": worker["worker_key"],
        "Worker Name": worker["worker_name"],
        "Schedule Date": schedule_date,
        "Site": site,
        "Task": task,
        "Start Time": start,
        "End Time": end,
        "Notes": _clean(body.get("notes"), 1_000),
    }


def _save(base, body: dict, session: dict) -> dict:
    workers = _workers(base)
    worker_key = _clean(body.get("worker_key"), 160)
    worker = workers.get(worker_key)
    if not worker:
        raise ValueError("Choose a valid worker.")
    if not worker["active"]:
        raise ValueError("This worker is inactive and cannot be scheduled.")
    current_rows = [_row(item) for item in base.records(TABLE, cache_seconds=0)]
    current = next(
        (item for item in current_rows if item["schedule_key"] == _clean(body.get("schedule_key"), 120)),
        None,
    )
    fields = _payload(body, worker, current)
    candidate = _row({"record_id": current.get("record_id", "") if current else "", "fields": fields})
    conflict = _conflict_reason(candidate, current_rows)
    now = _iso_now()
    status = "pending_approval" if conflict else "confirmed"
    if current and current["status"] == "confirmed" and conflict:
        status = "pending_approval"
    fields.update(
        {
            "Status": status,
            "Conflict Reason": conflict,
            "Submitted By": _clean(session.get("sub"), 160),
            "Submitted By Name": _clean(session.get("name"), 160),
            "Reviewed By": "" if conflict else current.get("reviewed_by", "") if current else "",
            "Reviewed By Name": "" if conflict else current.get("reviewed_by_name", "") if current else "",
            "Reviewed At": "" if conflict else current.get("reviewed_at", "") if current else "",
            "Created At": current.get("created_at", now) if current else now,
            "Updated At": now,
        }
    )
    saved = base.set_by_key(TABLE, KEY_FIELD, fields[KEY_FIELD], fields)
    stored = next(
        (_row(item) for item in base.records(TABLE, cache_seconds=0) if text_value(field(item, KEY_FIELD)) == fields[KEY_FIELD]),
        {**candidate, **{key.lower().replace(" ", "_"): value for key, value in fields.items()}},
    )
    return {
        "schedule": stored,
        "submitted_for_approval": status == "pending_approval",
        "conflict_reason": conflict,
        "created": bool(saved.get("created", False)),
    }


def _review(base, body: dict, session: dict) -> dict:
    key = _clean(body.get("schedule_key"), 120)
    rows = [_row(item) for item in base.records(TABLE, cache_seconds=0)]
    current = next((row for row in rows if row["schedule_key"] == key), None)
    if not current:
        raise ValueError("Choose a valid schedule request.")
    decision = _clean(body.get("decision"), 20).casefold()
    if decision not in {"approved", "rejected"}:
        raise ValueError("Choose Approve or Reject.")
    if decision == "approved":
        conflict = _conflict_reason({**current, "status": "confirmed"}, rows)
        if conflict:
            raise LarkAPIError(
                "Resolve the overlapping schedule before approving this request.", status=409,
            )
    now = _iso_now()
    fields = {
        "Schedule Key": current["schedule_key"],
        "Worker Key": current["worker_key"],
        "Worker Name": current["worker_name"],
        "Schedule Date": current["schedule_date"],
        "Site": current["site"],
        "Task": current["task"],
        "Start Time": current["start_time"],
        "End Time": current["end_time"],
        "Notes": current["notes"],
        "Status": decision,
        "Conflict Reason": "" if decision == "approved" else current["conflict_reason"],
        "Submitted By": current["submitted_by"],
        "Submitted By Name": current["submitted_by_name"],
        "Reviewed By": _clean(session.get("sub"), 160),
        "Reviewed By Name": _clean(session.get("name"), 160),
        "Reviewed At": now,
        "Created At": current["created_at"] or now,
        "Updated At": now,
    }
    base.set_by_key(TABLE, KEY_FIELD, key, fields)
    return {"schedule": _row({"record_id": current["record_id"], "fields": fields})}


def _cancel(base, body: dict, session: dict) -> dict:
    key = _clean(body.get("schedule_key"), 120)
    rows = [_row(item) for item in base.records(TABLE, cache_seconds=0)]
    current = next((row for row in rows if row["schedule_key"] == key), None)
    if not current:
        raise ValueError("Choose a valid schedule.")
    fields = {
        "Schedule Key": current["schedule_key"], "Worker Key": current["worker_key"],
        "Worker Name": current["worker_name"], "Schedule Date": current["schedule_date"],
        "Site": current["site"], "Task": current["task"], "Start Time": current["start_time"],
        "End Time": current["end_time"], "Notes": current["notes"], "Status": "cancelled",
        "Conflict Reason": current["conflict_reason"], "Submitted By": current["submitted_by"],
        "Submitted By Name": current["submitted_by_name"], "Reviewed By": _clean(session.get("sub"), 160),
        "Reviewed By Name": _clean(session.get("name"), 160), "Reviewed At": _iso_now(),
        "Created At": current["created_at"] or _iso_now(), "Updated At": _iso_now(),
    }
    base.set_by_key(TABLE, KEY_FIELD, key, fields)
    return {"schedule": _row({"record_id": current["record_id"], "fields": fields})}


def _range(query: dict) -> tuple[str, str]:
    today = date.today()
    start = _date((query.get("from") or [today.isoformat()])[0])
    end = _date((query.get("to") or [(today + timedelta(days=6)).isoformat()])[0])
    if start > end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 31:
        raise ValueError("Choose a schedule range of 32 days or fewer.")
    return start, end


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        session = _session(self)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        if not require_role(self, session, "schedule_manager"):
            return
        try:
            start, end = _range(parse_qs(urlparse(self.path).query))
            base = _ready_store()
            rows = [
                _row(record)
                for record in base.records(TABLE, cache_seconds=0)
                if start <= _row(record)["schedule_date"] <= end
            ]
            rows.sort(key=lambda row: (row["schedule_date"], row["start_time"] or "99:99", row["worker_name"].casefold(), row["site"].casefold()))
            json_response(self, {
                "from": start, "to": end, "rows": rows,
                "pending_count": sum(row["status"] == "pending_approval" for row in rows),
            })
        except (ValueError, TypeError) as error:
            json_response(self, {"error": str(error)}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)

    def do_POST(self) -> None:
        session = _session(self)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        if not require_role(self, session, "schedule_manager"):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            base = _ready_store()
            action = _clean(body.get("action"), 30).casefold()
            if action in {"save", "submit"}:
                result = _save(base, body, session)
                json_response(self, result, 202 if result["submitted_for_approval"] else 200)
            elif action == "review":
                json_response(self, _review(base, body, session))
            elif action == "cancel":
                json_response(self, _cancel(base, body, session))
            else:
                raise ValueError("Choose save, review, or cancel.")
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": str(error)}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)
