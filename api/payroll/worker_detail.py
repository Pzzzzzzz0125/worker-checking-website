from __future__ import annotations

import re
from datetime import date
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._lark_base import LarkBase
from api._reports import aggregate, california_overtime, load_report_data, pay_period
from api._shared import cookie_value, json_response, verify_payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        month = query.get("month", [date.today().strftime("%Y-%m")])[0]
        half = query.get("half", ["1"])[0]
        worker_id = query.get("worker_id", [""])[0]
        if not re.fullmatch(r"\d{4}-\d{2}", month) or not worker_id.isdigit():
            json_response(self, {"error": "Choose a valid worker and month."}, 400)
            return
        try:
            start, end = pay_period(month, half)
            data = load_report_data(LarkBase())
            worker = next((item for item in data["workers"].values() if item["id"] == int(worker_id)), None)
            if not worker:
                raise ValueError("Choose a valid worker.")
            selected = [
                dict(item) for item in data["days"]
                if item["worker_key"] == worker["key"]
                and item["status"] == "worked"
                and start.isoformat() <= item["date"] <= end.isoformat()
            ]
            breakdown = california_overtime(data["days"], worker["key"], start, end, worker["worker_type"])
            for day in selected:
                part = breakdown.get(day["date"], {
                    "regular_hours": day["total_hours"], "overtime_hours": 0,
                    "doubletime_hours": 0, "weighted_hours": day["total_hours"],
                })
                day.update(part)
                day["estimated_salary"] = round(part["weighted_hours"] * worker["daily_rate"] / 8.0 + day["extra_pay"], 2)
            selected.sort(key=lambda item: item["date"])
            json_response(
                self,
                {
                    "worker": worker,
                    "period": {"from": start.isoformat(), "to": end.isoformat(), "month": month, "half": half},
                    "totals": {
                        "hours": round(sum(item["total_hours"] for item in selected), 2),
                        "regular_hours": round(sum(item["regular_hours"] for item in selected), 2),
                        "overtime_hours": round(sum(item["overtime_hours"] for item in selected), 2),
                        "doubletime_hours": round(sum(item["doubletime_hours"] for item in selected), 2),
                        "weighted_hours": round(sum(item["weighted_hours"] for item in selected), 2),
                        "days": len(selected),
                        "estimated_salary": round(sum(item["estimated_salary"] for item in selected), 2),
                    },
                    "days": selected,
                    "locations": aggregate(selected, "locations"),
                    "cost_centers": aggregate(selected, "cost_centers"),
                },
            )
        except (ValueError, LarkAPIError) as error:
            status = error.status if isinstance(error, LarkAPIError) else 400
            json_response(self, {"error": str(error)}, status)
