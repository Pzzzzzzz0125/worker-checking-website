from __future__ import annotations

import calendar
from datetime import timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._reports import california_overtime, load_report_data, report_period
from api._shared import cookie_value, json_response, verify_payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        try:
            start, end = report_period(query)
            worker_id = query.get("worker_id", [""])[0]
            if worker_id and not worker_id.isdigit():
                raise ValueError("Choose a valid worker.")
            query_start = start - timedelta(days=start.weekday())
            query_end = end + timedelta(days=6 - end.weekday())
            data = load_report_data(
                DataStore(), query_start, query_end, worker_key=worker_id,
                check_period_start=start,
            )
            legacy_period = (
                start.year == end.year
                and start.month == end.month
                and (
                    (start.day == 1 and end.day == 15)
                    or (
                        start.day == 16
                        and end.day == calendar.monthrange(end.year, end.month)[1]
                    )
                )
            )
            workers = []
            for worker_key, worker in data["workers"].items():
                period_days = [
                    item for item in data["days"]
                    if item["worker_key"] == worker_key and start.isoformat() <= item["date"] <= end.isoformat()
                ]
                if not period_days:
                    continue
                worked = [item for item in period_days if item["status"] == "worked"]
                sick_leave = [item for item in period_days if item["status"] == "sick_leave"]
                sick_hours = round(
                    sum(float(item.get("total_hours") or 8) for item in sick_leave), 2,
                )
                breakdown = california_overtime(data["days"], worker_key, start, end, worker["worker_type"])
                parts = list(breakdown.values())
                regular = round(sum(item["regular_hours"] for item in parts) + sick_hours, 2)
                overtime = round(sum(item["overtime_hours"] for item in parts), 2)
                doubletime = round(sum(item["doubletime_hours"] for item in parts), 2)
                weighted = round(sum(item["weighted_hours"] for item in parts) + sick_hours, 2)
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
                        "sick_leave_days": len(sick_leave),
                        "sick_leave_hours": sick_hours,
                        "off_days": len([item for item in period_days if item["status"] == "off"]),
                        "hours": round(sum(item["total_hours"] for item in worked) + sick_hours, 2),
                        "regular_hours": regular,
                        "overtime_hours": overtime,
                        "doubletime_hours": doubletime,
                        "weighted_hours": weighted,
                        "extra_pay": extra,
                        "estimated_salary": round(weighted * rate / 8.0 + extra, 2),
                        "checked": data["checks"].get(
                            (worker_key, start.isoformat(), end.isoformat()),
                            data["checks"].get((worker_key, start.isoformat()), False)
                            if legacy_period else False,
                        ),
                    }
                )
            workers.sort(key=lambda item: item["worker_name"].casefold())
            json_response(
                self,
                {
                    "period": {"from": start.isoformat(), "to": end.isoformat()},
                    "totals": {
                        "hours": round(sum(item["hours"] for item in workers), 2),
                        "regular_hours": round(sum(item["regular_hours"] for item in workers), 2),
                        "weighted_hours": round(sum(item["weighted_hours"] for item in workers), 2),
                        "estimated_salary": round(sum(item["estimated_salary"] for item in workers), 2),
                        "workers": len([
                            item for item in workers
                            if item["worked_days"] or item["sick_leave_days"]
                        ]),
                        "checked": len([item for item in workers if item["checked"]]),
                    },
                    "workers": workers,
                },
            )
        except (ValueError, LarkAPIError) as error:
            status = error.status if isinstance(error, LarkAPIError) else 400
            json_response(self, {"error": str(error)}, status)
