from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._lark_sync import synchronize_lark
from api._postgres_base import PostgresBase, lark_mirror_enabled
from api._shared import json_response
from report_handlers.workers import admin_ids, session


def _signed_in(handler: BaseHTTPRequestHandler) -> dict | None:
    current = session(handler)
    if not current:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return None
    return current


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        current = _signed_in(self)
        if not current:
            return
        try:
            details = parse_qs(urlparse(self.path).query).get("details", [""])[0]
            include_errors = details in {"1", "true", "yes"}
            if include_errors and current.get("sub") not in admin_ids():
                json_response(self, {"error": "Only a configured Lark administrator can view sync errors."}, 403)
                return
            result = PostgresBase().sync_status(include_errors=include_errors)
            if not result["enabled"]:
                result["message"] = "Lark mirroring is disabled; the queue is preserved but not processed."
            json_response(self, result)
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)

    def do_POST(self) -> None:
        current = _signed_in(self)
        if not current:
            return
        if not lark_mirror_enabled():
            json_response(
                self,
                {
                    "enabled": False,
                    "processed": 0,
                    "message": "Lark mirroring is disabled.",
                },
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            queued = 0
            if body.get("backfill") or body.get("work_log_backfill"):
                if current.get("sub") not in admin_ids():
                    json_response(
                        self,
                        {"error": "Only a configured Lark administrator can queue a snapshot."},
                        403,
                    )
                    return
                database = PostgresBase()
                queued = (
                    database.enqueue_work_log_snapshot()
                    if body.get("work_log_backfill")
                    else database.enqueue_sync_snapshot()
                )
            result = synchronize_lark(int(body.get("limit") or 200))
            json_response(self, {**result, "snapshot_queued": queued})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid Lark sync request: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)
