from __future__ import annotations

import re
from datetime import date
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._lark_base import LarkBase
from api._reports import california_overtime, load_report_data, pay_period
from api._shared import cookie_value, json_response, verify_payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        month = query.get("month", [date.today().strftime("%Y-%m")])[0]
        half = query.get("half", ["1" if date.today().day <= 15 else "2"])[0]
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            json_response(self, {"error": "Choose a valid month."}, 400)
            return
        try:
            start, end = pay_period(month, half)
            data = load_report_data(LarkBase())
            workers = []
            for worker_key, worker in data["workers"].items():
                period_days = [
                    item for item in data["days"]
                    if item["worker_key"] == worker_key and start.isoformat() <= item["date"] <= end.isoformat()
                ]
                if not period_days:
                    continue
                worked = [item for item in period_days if item["status"] == "worked"]
                breakdown = california_overtime(data["days"], worker_key, start, end, worker["worker_type"])
                parts = list(breakdown.values())
                regular = round(sum(item["regular_hours"] for item in parts), 2)
                overtime = round(sum(item["overtime_hours"] for item in parts), 2)
                doubletime = round(sum(item["doubletime_hours"] for item in parts), 2)
                weighted = round(sum(item["weighted_hours"] for item in parts), 2)
                extra = round(sum(item["extra_pay"] for item in worked), 2)
                rate = float(worker["daily_rate"])
                workers.append(
                    {
                        "worker_id": worker["id"],
                        "worker_name": worker["name"],
                        "worker_type": worker["worker_type"],
                        "daily_rate": rate,
                        "recorded_days": len(period_days),
                        "worked_days": len(worked),
                        "off_days": len([item for item in period_days if item["status"] == "off"]),
                        "hours": round(sum(item["total_hours"] for item in worked), 2),
                        "regular_hours": regular,
                        "overtime_hours": overtime,
                        "doubletime_hours": doubletime,
                        "weighted_hours": weighted,
                        "extra_pay": extra,
                        "estimated_salary": round(weighted * rate / 8.0 + extra, 2),
                        "checked": data["checks"].get((worker_key, start.isoformat()), False),
                    }
                )
            workers.sort(key=lambda item: item["worker_name"].casefold())
            json_response(
                self,
                {
                    "period": {"month": month, "half": half, "from": start.isoformat(), "to": end.isoformat()},
                    "totals": {
                        "hours": round(sum(item["hours"] for item in workers), 2),
                        "estimated_salary": round(sum(item["estimated_salary"] for item in workers), 2),
                        "workers": len([item for item in workers if item["worked_days"]]),
                        "checked": len([item for item in workers if item["checked"]]),
                    },
                    "workers": workers,
                },
            )
        except (ValueError, LarkAPIError) as error:
            status = error.status if isinstance(error, LarkAPIError) else 400
            json_response(self, {"error": str(error)}, status)
