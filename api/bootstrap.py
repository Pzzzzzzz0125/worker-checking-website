from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import BaseHTTPRequestHandler

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._lark_base import (
    LarkBase,
    bool_value,
    date_value,
    field,
    text_value,
    worker_id,
)
from api._shared import cookie_value, json_response, verify_payload
from report_handlers.sites import active_site_names


def build_bootstrap(base: LarkBase) -> dict:
    missing = base.missing_tables()
    if missing:
        raise LarkAPIError(
            "Database setup is incomplete. Missing: " + ", ".join(missing),
            status=503,
        )

    # Fetch independent tables together. On Lark-backed deployments these are
    # network requests, so serial reads made every refresh noticeably slower.
    with ThreadPoolExecutor(max_workers=2) as executor:
        workers_future = executor.submit(base.records, "Workers", cache_seconds=0)
        centers_future = executor.submit(base.records, "Cost Centers")
        worker_records = workers_future.result()
        center_records = centers_future.result()

    workers = []
    for index, record in enumerate(worker_records, start=1):
        name = text_value(field(record, "Name"))
        if not name or not bool_value(field(record, "Active"), True):
            continue
        workers.append(
            {
                "id": worker_id(field(record, "Worker Key"), index),
                "worker_key": text_value(field(record, "Worker Key")),
                "name": name,
                "active": 1 if bool_value(field(record, "Active"), True) else 0,
            }
        )
    workers.sort(key=lambda item: item["name"].casefold())

    cost_centers = []
    for record in center_records:
        center_id = text_value(field(record, "Cost Center ID"))
        name = text_value(field(record, "Name"))
        if center_id and name and bool_value(field(record, "Active"), True):
            cost_centers.append({"id": center_id, "name": name})
    cost_centers.sort(key=lambda item: (item["name"].casefold(), item["id"]))

    return {
        "workers": workers,
        "cost_centers": cost_centers,
        "locations": [],
        "ai_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        "last_recorded_date": "",
        "workbook_year": date.today().year,
    }


def build_bootstrap_details(base: LarkBase) -> dict:
    if hasattr(base, "table_ids"):
        base.table_ids()
    with ThreadPoolExecutor(max_workers=2) as executor:
        sites_future = executor.submit(active_site_names, base, seed_if_empty=True)
        days_future = executor.submit(
            base.records, "Work Days", field_names=("Work Date",), cache_seconds=60,
        )
        try:
            locations = sites_future.result()
        except LarkAPIError:
            # Older Lark-only deployments can continue using historical Site
            # values until an administrator runs the updated Base setup.
            location_records = base.records(
                "Location Entries", field_names=("Location",), cache_seconds=300,
            )
            locations = sorted(
                {
                    text_value(field(record, "Location"))
                    for record in location_records
                    if text_value(field(record, "Location"))
                },
                key=str.casefold,
            )
        work_days = days_future.result()
    dates = [date_value(field(record, "Work Date")) for record in work_days]
    dates = [value for value in dates if value]
    last_recorded = max(dates, default="")
    return {
        "locations": locations,
        "last_recorded_date": last_recorded,
        "workbook_year": int(last_recorded[:4]) if last_recorded else date.today().year,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        session = verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            json_response(self, build_bootstrap(DataStore()))
        except LarkAPIError as error:
            json_response(
                self,
                {
                    "error": str(error),
                    "code": "setup_required" if error.status == 503 else "storage_error",
                    "setup_required": error.status == 503,
                    "lark_code": error.code,
                },
                error.status,
            )
