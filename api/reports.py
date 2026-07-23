from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._shared import json_response
from report_handlers.entries import handler as EntryHandler
from report_handlers.ai import handler as AiHandler
from report_handlers.location_detail import handler as LocationDetailHandler
from report_handlers.payroll import handler as PayrollHandler
from report_handlers.payroll_check import handler as PayrollCheckHandler
from report_handlers.payroll_worker_detail import handler as PayrollWorkerDetailHandler
from report_handlers.workers import handler as WorkersHandler, require_payroll_access


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
            "workers_access": WorkersHandler,
            "payroll_access": WorkersHandler,
        }
        selected = actions.get(self.action())
        if selected is None:
            json_response(self, {"error": "Unknown report route."}, 404)
            return
        if self.action() in {"payroll", "payroll_worker_detail"} and not require_payroll_access(self):
            return
        selected.do_GET(self)

    def do_POST(self) -> None:
        if self.action() in {"ai_parse", "ai_apply"}:
            AiHandler.do_POST(self)
            return
        if self.action() in {"day", "day_clear", "worker_days", "worker_days_copy"}:
            EntryHandler.do_POST(self)
            return
        if self.action() in {"workers", "workers_unlock", "payroll_unlock"}:
            WorkersHandler.do_POST(self)
            return
        if self.action() != "payroll_check":
            json_response(self, {"error": "Unknown report route."}, 404)
            return
        if not require_payroll_access(self):
            return
        PayrollCheckHandler.do_POST(self)
