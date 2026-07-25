from __future__ import annotations

import json
import hmac
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._lark_base import (
    LarkBase,
    bool_value,
    field,
    number_value,
    text_value,
    formula_string,
    worker_id,
)
from api._shared import (
    cookie_header,
    cookie_value,
    json_response,
    secure_cookie,
    sign_payload,
    verify_payload,
)
from worklog_parser import normalize_name


def worker_profile(record: dict, fallback_id: int = 0) -> dict:
    key = text_value(field(record, "Worker Key"))
    worker_type = text_value(field(record, "Worker Type")).upper().replace("-", "")
    return {
        "id": worker_id(key, fallback_id),
        "worker_key": key,
        "name": text_value(field(record, "Name")),
        "normalized_name": text_value(field(record, "Normalized Name")),
        "worker_type": worker_type if worker_type in {"W2", "1099"} else "1099",
        "active": bool_value(field(record, "Active"), True),
        "daily_rate": round(number_value(field(record, "Daily Rate")), 2),
        "display_order": int(number_value(field(record, "Display Order"), fallback_id)),
        "aliases": text_value(field(record, "Aliases")),
        "notes": text_value(field(record, "Notes")),
    }


def list_workers(base: LarkBase) -> list[dict]:
    workers = [
        worker_profile(record, index)
        for index, record in enumerate(base.records("Workers", cache_seconds=0), start=1)
    ]
    return sorted(
        [worker for worker in workers if worker["worker_key"] and worker["name"]],
        key=lambda worker: (
            not worker["active"],
            worker["display_order"],
            worker["name"].casefold(),
        ),
    )


def _worker_fields(body: dict, key: str, default_order: int = 0) -> dict:
    name = " ".join(str(body.get("name") or "").split())
    if not name or len(name) > 120:
        raise ValueError("Worker name is required and must be 120 characters or fewer.")
    worker_type = str(body.get("worker_type") or "").upper().replace("-", "")
    if worker_type not in {"W2", "1099"}:
        raise ValueError("Worker type must be W-2 or 1099.")
    if not isinstance(body.get("active"), bool):
        raise ValueError("Active status must be true or false.")
    try:
        daily_rate = round(float(body.get("daily_rate") or 0), 2)
        display_order = int(float(body.get("display_order") or default_order))
    except (TypeError, ValueError):
        raise ValueError("Daily rate and display order must be numbers.") from None
    if daily_rate < 0 or daily_rate > 1_000_000:
        raise ValueError("Daily rate must be between 0 and 1,000,000.")
    if display_order < 0 or display_order > 1_000_000:
        raise ValueError("Display order must be between 0 and 1,000,000.")
    aliases = str(body.get("aliases") or "").strip()
    notes = str(body.get("notes") or "").strip()
    if len(aliases) > 2_000 or len(notes) > 5_000:
        raise ValueError("Aliases or notes are too long.")

    return {
        "Worker Key": key,
        "Name": name,
        "Normalized Name": normalize_name(name),
        "Worker Type": worker_type,
        "Active": body["active"],
        "Daily Rate": daily_rate,
        "Display Order": display_order,
        "Aliases": aliases,
        "Notes": notes,
    }


def update_worker(base: LarkBase, body: dict) -> dict:
    key = str(body.get("worker_key") or "").strip()
    existing = {worker["worker_key"]: worker for worker in list_workers(base)}
    if not key or key not in existing:
        raise ValueError("Choose a valid worker.")
    fields = _worker_fields(body, key, existing[key]["display_order"])
    base.set_by_key("Workers", "Worker Key", key, fields)
    return {
        **existing[key],
        **{
            "name": fields["Name"],
            "normalized_name": fields["Normalized Name"],
            "worker_type": fields["Worker Type"],
            "active": fields["Active"],
            "daily_rate": fields["Daily Rate"],
            "display_order": fields["Display Order"],
            "aliases": fields["Aliases"],
            "notes": fields["Notes"],
        },
    }


def create_worker(base: LarkBase, body: dict) -> dict:
    existing = list_workers(base)
    used_keys = {worker["worker_key"] for worker in existing}
    numeric_keys = [int(key) for key in used_keys if key.isdigit()]
    key = str(max(numeric_keys, default=0) + 1)
    while key in used_keys:
        key = str(int(key) + 1)
    default_order = max(
        (worker["display_order"] for worker in existing),
        default=0,
    ) + 1
    fields = _worker_fields(body, key, default_order)
    normalized = fields["Normalized Name"]
    if normalized in {worker["normalized_name"] for worker in existing}:
        raise ValueError("A worker with this name already exists.")
    saved = base.set_by_key("Workers", "Worker Key", key, fields)
    return {
        "id": worker_id(key, len(existing) + 1),
        "worker_key": key,
        "name": fields["Name"],
        "normalized_name": normalized,
        "worker_type": fields["Worker Type"],
        "active": fields["Active"],
        "daily_rate": fields["Daily Rate"],
        "display_order": fields["Display Order"],
        "aliases": fields["Aliases"],
        "notes": fields["Notes"],
        "created": bool(saved.get("created", True)),
    }


def remove_worker(base: LarkBase, body: dict) -> dict:
    key = str(body.get("worker_key") or "").strip()
    records = base.records("Workers", cache_seconds=0)
    match = next(
        (
            record for record in records
            if text_value(field(record, "Worker Key")) == key
        ),
        None,
    )
    if not match:
        raise ValueError("Choose a valid worker.")
    work_history = base.records(
        "Work Days",
        filter_formula=(
            f"CurrentValue.[Worker Key]={formula_string(key)}"
        ),
        field_names=("Work Day Key",),
        cache_seconds=0,
    )
    payroll_history = base.records(
        "Payroll Checks",
        filter_formula=(
            f"CurrentValue.[Worker Key]={formula_string(key)}"
        ),
        field_names=("Payroll Check Key",),
        cache_seconds=0,
    )
    history_records = len(work_history) + len(payroll_history)
    if history_records:
        profile = worker_profile(match)
        profile["active"] = False
        archived = update_worker(base, profile)
        return {
            "removed": True,
            "mode": "archived",
            "history_records": history_records,
            "worker": archived,
        }
    deleted = base.delete_record_ids(
        "Workers",
        [str(match.get("record_id") or "")],
    )
    return {
        "removed": bool(deleted),
        "mode": "deleted",
        "history_records": 0,
        "worker_key": key,
    }


def session(handler: BaseHTTPRequestHandler) -> dict | None:
    return verify_payload(cookie_value(handler, "workforce_session"), 12 * 60 * 60)


def admin_ids() -> set[str]:
    return {
        value.strip()
        for value in os.environ.get("LARK_ADMIN_OPEN_IDS", "").split(",")
        if value.strip()
    }


def access_status(handler: BaseHTTPRequestHandler, current_session: dict) -> dict:
    is_lark_admin = current_session.get("sub") in admin_ids()
    password_session = verify_payload(
        cookie_value(handler, "worker_admin_session"), 8 * 60 * 60,
    )
    has_password_access = bool(
        password_session
        and password_session.get("scope") == "worker-management"
        and password_session.get("sub") == current_session.get("sub")
    )
    return {
        "authorized": is_lark_admin or has_password_access,
        "access_type": (
            "lark_admin" if is_lark_admin
            else "password" if has_password_access
            else ""
        ),
        "password_configured": bool(
            os.environ.get("WORKER_ADMIN_PASSWORD", "").strip()
        ),
        "admin_allowlist_configured": bool(admin_ids()),
    }


def payroll_access_status(handler: BaseHTTPRequestHandler, current_session: dict) -> dict:
    """Payroll is intentionally a separate, read-sensitive permission scope."""
    is_lark_admin = current_session.get("sub") in admin_ids()
    password_session = verify_payload(
        cookie_value(handler, "payroll_access_session"), 8 * 60 * 60,
    )
    has_password_access = bool(
        password_session
        and password_session.get("scope") == "payroll-check"
        and password_session.get("sub") == current_session.get("sub")
    )
    return {
        "authorized": is_lark_admin or has_password_access,
        "access_type": "lark_admin" if is_lark_admin else "password" if has_password_access else "",
        "password_configured": bool(os.environ.get("PAYROLL_PASSWORD", "").strip()),
        "admin_allowlist_configured": bool(admin_ids()),
    }


def require_payroll_access(handler: BaseHTTPRequestHandler) -> bool:
    current_session = session(handler)
    if not current_session:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return False
    access = payroll_access_status(handler, current_session)
    if access["authorized"]:
        return True
    json_response(handler, {"error": "Payroll Check requires authorized access.", "code": "payroll_access_required", **access}, 403)
    return False


def action(handler: BaseHTTPRequestHandler) -> str:
    return parse_qs(urlparse(handler.path).query).get("action", [""])[0]


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        current_session = session(self)
        if not current_session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        access = access_status(self, current_session)
        if action(self) == "workers_access":
            json_response(self, access)
            return
        if action(self) == "payroll_access":
            json_response(self, payroll_access_status(self, current_session))
            return
        if not access["authorized"]:
            json_response(
                self,
                {
                    "error": "Worker Management requires administrator access.",
                    "code": "worker_admin_required",
                    **access,
                },
                403,
            )
            return
        try:
            workers = list_workers(DataStore())
            json_response(
                self,
                {
                    "workers": workers,
                    "totals": {
                        "workers": len(workers),
                        "active": sum(worker["active"] for worker in workers),
                        "w2": sum(worker["worker_type"] == "W2" for worker in workers),
                        "contractors": sum(
                            worker["worker_type"] == "1099" for worker in workers
                        ),
                    },
                },
            )
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)

    def do_POST(self) -> None:
        current_session = session(self)
        if not current_session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            if action(self) == "workers_unlock":
                configured = os.environ.get("WORKER_ADMIN_PASSWORD", "").strip()
                supplied = str(body.get("password") or "")
                if not configured:
                    json_response(
                        self,
                        {
                            "error": "WORKER_ADMIN_PASSWORD is not configured in Vercel.",
                            "code": "worker_password_not_configured",
                        },
                        503,
                    )
                    return
                if not hmac.compare_digest(supplied, configured):
                    json_response(self, {"error": "Incorrect Worker Management password."}, 403)
                    return
                grant = sign_payload(
                    {
                        "sub": current_session.get("sub", ""),
                        "scope": "worker-management",
                        "iat": int(time.time()),
                    }
                )
                json_response(
                    self,
                    {"authorized": True, "access_type": "password"},
                    headers={
                        "Set-Cookie": cookie_header(
                            "worker_admin_session",
                            grant,
                            8 * 60 * 60,
                            secure_cookie(self),
                        )
                    },
                )
                return
            if action(self) == "payroll_unlock":
                configured = os.environ.get("PAYROLL_PASSWORD", "").strip()
                supplied = str(body.get("password") or "")
                if not configured:
                    json_response(self, {"error": "PAYROLL_PASSWORD is not configured in Vercel.", "code": "payroll_password_not_configured"}, 503)
                    return
                if not hmac.compare_digest(supplied, configured):
                    json_response(self, {"error": "Incorrect Payroll Check password."}, 403)
                    return
                grant = sign_payload({"sub": current_session.get("sub", ""), "scope": "payroll-check", "iat": int(time.time())})
                json_response(self, {"authorized": True, "access_type": "password"}, headers={"Set-Cookie": cookie_header("payroll_access_session", grant, 8 * 60 * 60, secure_cookie(self))})
                return
            access = access_status(self, current_session)
            if not access["authorized"]:
                json_response(
                    self,
                    {
                        "error": "Worker Management requires administrator access.",
                        "code": "worker_admin_required",
                        **access,
                    },
                    403,
                )
                return
            base = DataStore()
            selected_action = action(self)
            if selected_action == "worker_delete":
                json_response(self, remove_worker(base, body))
                return
            worker = (
                update_worker(base, body)
                if str(body.get("worker_key") or "").strip()
                else create_worker(base, body)
            )
            json_response(self, {"saved": True, "worker": worker})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid worker profile: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
