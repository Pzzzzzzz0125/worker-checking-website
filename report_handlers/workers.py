from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from api._lark import LarkAPIError
from api._lark_base import (
    LarkBase,
    bool_value,
    field,
    number_value,
    text_value,
    worker_id,
)
from api._shared import cookie_value, json_response, verify_payload
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


def update_worker(base: LarkBase, body: dict) -> dict:
    key = str(body.get("worker_key") or "").strip()
    existing = {worker["worker_key"]: worker for worker in list_workers(base)}
    if not key or key not in existing:
        raise ValueError("Choose a valid worker.")

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
        display_order = int(float(body.get("display_order") or 0))
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

    fields = {
        "Name": name,
        "Normalized Name": normalize_name(name),
        "Worker Type": worker_type,
        "Active": body["active"],
        "Daily Rate": daily_rate,
        "Display Order": display_order,
        "Aliases": aliases,
        "Notes": notes,
    }
    base.set_by_key("Workers", "Worker Key", key, fields)
    return {
        **existing[key],
        **{
            "name": name,
            "normalized_name": fields["Normalized Name"],
            "worker_type": worker_type,
            "active": body["active"],
            "daily_rate": daily_rate,
            "display_order": display_order,
            "aliases": aliases,
            "notes": notes,
        },
    }


def session(handler: BaseHTTPRequestHandler) -> dict | None:
    return verify_payload(cookie_value(handler, "workforce_session"), 12 * 60 * 60)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not session(self):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            workers = list_workers(LarkBase())
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
        if not session(self):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            json_response(
                self,
                {"saved": True, "worker": update_worker(LarkBase(), body)},
            )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid worker profile: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
