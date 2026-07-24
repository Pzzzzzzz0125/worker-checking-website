from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from api._lark import LarkAPIError
from api._lark_base import LarkBase
from api._postgres_base import KEY_FIELDS, PostgresBase
from api._shared import json_response
from report_handlers.workers import admin_ids, session


def _authorize(handler: BaseHTTPRequestHandler) -> dict | None:
    current = session(handler)
    if not current:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return None
    if current.get("sub") not in admin_ids():
        json_response(
            handler,
            {"error": "Database setup requires a configured Lark administrator."},
            403,
        )
        return None
    return current


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not _authorize(self):
            return
        configured = bool(os.environ.get("DATABASE_URL", "").strip())
        if not configured:
            json_response(
                self,
                {
                    "configured": False,
                    "backend": os.environ.get("DATA_BACKEND", "lark"),
                    "error": "DATABASE_URL is not configured.",
                },
                503,
            )
            return
        try:
            database = PostgresBase()
            missing = database.missing_tables()
            counts = {
                table_name: len(database.records(table_name, cache_seconds=0))
                for table_name in sorted(KEY_FIELDS)
            } if not missing else {}
            json_response(
                self,
                {
                    "configured": True,
                    "ready": not missing,
                    "backend": os.environ.get("DATA_BACKEND", "lark"),
                    "missing_tables": missing,
                    "counts": counts,
                },
            )
        except LarkAPIError as error:
            json_response(
                self,
                {
                    "configured": True,
                    "ready": False,
                    "backend": os.environ.get("DATA_BACKEND", "lark"),
                    "error": str(error),
                },
                error.status,
            )

    def do_POST(self) -> None:
        if not _authorize(self):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if body.get("confirm") != "INITIALIZE POSTGRES":
                raise ValueError("Confirmation text must be INITIALIZE POSTGRES.")
            database = PostgresBase()
            database.ensure_schema()
            copied = {}
            if body.get("copy_from_lark", True):
                source = LarkBase()
                for table_name in KEY_FIELDS:
                    copied[table_name] = database.import_records(
                        table_name,
                        source.records(table_name, cache_seconds=0),
                    )
            counts = {
                table_name: len(database.records(table_name, cache_seconds=0))
                for table_name in sorted(KEY_FIELDS)
            }
            json_response(
                self,
                {
                    "ready": True,
                    "copied": copied,
                    "counts": counts,
                    "next_step": "Set DATA_BACKEND=postgres and redeploy.",
                },
            )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid database setup: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)
