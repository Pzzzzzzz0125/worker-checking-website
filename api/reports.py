from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._shared import json_response
from report_handlers.entries import handler as EntryHandler
from report_handlers.location_detail import handler as LocationDetailHandler
from report_handlers.payroll import handler as PayrollHandler
from report_handlers.payroll_check import handler as PayrollCheckHandler
from report_handlers.payroll_worker_detail import handler as PayrollWorkerDetailHandler
from report_handlers.workers import handler as WorkersHandler


class handler(BaseHTTPRequestHandler):
    def action(self) -> str:
        return parse_qs(urlparse(self.path).query).get("action", [""])[0]

    def do_GET(self) -> None:
        actions = {
            "payroll": PayrollHandler,
            "payroll_worker_detail": PayrollWorkerDetailHandler,
            "location_detail": LocationDetailHandler,
            "day": EntryHandler,
            "worker_month": EntryHandler,
            "workers": WorkersHandler,
        }
        selected = actions.get(self.action())
        if selected is None:
            json_response(self, {"error": "Unknown report route."}, 404)
            return
        selected.do_GET(self)

    def do_POST(self) -> None:
        if self.action() in {"day", "day_clear", "worker_days", "worker_days_copy"}:
            EntryHandler.do_POST(self)
            return
        if self.action() == "workers":
            WorkersHandler.do_POST(self)
            return
        if self.action() != "payroll_check":
            json_response(self, {"error": "Unknown report route."}, 404)
            return
        PayrollCheckHandler.do_POST(self)
