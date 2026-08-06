from __future__ import annotations

import json
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._permissions import require_role
from api._shared import cookie_value, json_response, verify_payload


def date_millis(value: date) -> int:
    return int(datetime.combine(value, datetime.min.time(), ZoneInfo("America/Los_Angeles")).timestamp() * 1000)


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        session = verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        if not require_role(self, session, "entry_user"):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            worker_id = int(body.get("worker_id") or 0)
            start = date.fromisoformat(str(body.get("period_start") or ""))
            end = date.fromisoformat(str(body.get("period_end") or ""))
            if worker_id <= 0 or start > end or (end - start).days > 366:
                raise ValueError("Choose a valid worker and date range.")
            checked = bool(body.get("checked"))
            key = f"{worker_id}|{start.isoformat()}|{end.isoformat()}"
            now = int(datetime.now(tz=ZoneInfo("America/Los_Angeles")).timestamp() * 1000)
            result = DataStore().set_by_key(
                "Payroll Checks",
                "Payroll Check Key",
                key,
                {
                    "Payroll Check Key": key,
                    "Worker Key": str(worker_id),
                    "Period Start": date_millis(start),
                    "Period End": date_millis(end),
                    "Checked": checked,
                    "Checked By": session.get("name") or session.get("sub", ""),
                    "Checked At": now,
                },
            )
            json_response(self, {"saved": True, "checked": checked, **result})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid payroll check: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
