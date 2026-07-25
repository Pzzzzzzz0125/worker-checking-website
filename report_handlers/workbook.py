from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler

from api._lark import LarkAPIError
from api._lark_sheet import (
    WORKBOOK_SETTING,
    LarkWorkbook,
    configured_workbook,
    worker_profiles,
)
from api._postgres_base import PostgresBase
from api._shared import json_response
from api._work_log import work_log_row
from report_handlers.workers import admin_ids, session


def _authorize(handler: BaseHTTPRequestHandler) -> dict | None:
    current = session(handler)
    if not current:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return None
    if current.get("sub") not in admin_ids():
        json_response(
            handler,
            {"error": "Workbook setup requires a configured Lark administrator."},
            403,
        )
        return None
    return current


def _fields(records: list[dict]) -> list[dict]:
    return [
        record.get("fields") or {}
        for record in records
        if isinstance(record.get("fields"), dict)
    ]


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not _authorize(self):
            return
        try:
            database = PostgresBase()
            configured = configured_workbook(database)
            if not configured:
                json_response(
                    self,
                    {
                        "configured": False,
                        "title": "Speed Construction Work Schedule",
                    },
                )
                return
            workbook, config = configured
            json_response(
                self,
                {
                    "configured": True,
                    "title": config.get("title") or "Speed Construction Work Schedule",
                    "url": workbook.url,
                    "workers": len(config.get("worker_rows") or {}),
                    "sheets": len(workbook.sheets()),
                },
            )
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)

    def do_POST(self) -> None:
        if not _authorize(self):
            return
        try:
            if os.environ.get("DATA_BACKEND", "").strip().casefold() != "postgres":
                raise LarkAPIError(
                    "The connected workbook requires PostgreSQL as the data backend.",
                    status=409,
                )
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            if body.get("action") not in {"initialize", "refresh"}:
                raise ValueError("Action must be initialize or refresh.")

            database = PostgresBase()
            database.ensure_schema()
            configured = configured_workbook(database)
            if configured:
                workbook, config = configured
                created = False
            else:
                workbook, config = LarkWorkbook.create()
                database.set_setting(WORKBOOK_SETTING, config)
                created = True

            workers = worker_profiles(
                database.records("Workers", cache_seconds=0)
            )
            day_fields = _fields(
                database.records("Work Days", cache_seconds=0)
            )
            day_keys = [
                str(day.get("Work Day Key") or "")
                for day in day_fields
                if day.get("Work Day Key")
            ]
            days, locations = database.work_log_records(day_keys)
            locations_by_day: dict[str, list[dict]] = {}
            for location in locations:
                key = str(location.get("Work Day Key") or "")
                if key:
                    locations_by_day.setdefault(key, []).append(location)
            rows = [
                work_log_row(
                    day,
                    locations_by_day.get(str(day.get("Work Day Key") or ""), []),
                )
                for day in days
            ]
            result = workbook.initialize(workers, rows, config)
            config.update(
                {
                    "spreadsheet_token": workbook.spreadsheet_token,
                    "url": workbook.url,
                    "title": "Speed Construction Work Schedule",
                    "worker_rows": result["worker_rows"],
                }
            )
            database.set_setting(WORKBOOK_SETTING, config)
            json_response(
                self,
                {
                    "configured": True,
                    "created": created,
                    "url": workbook.url,
                    "title": config["title"],
                    "periods": result["periods"],
                    "workers": result["workers"],
                    "work_cells": result["work_cells"],
                },
            )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid workbook request: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)
