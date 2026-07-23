from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._lark_base import LarkBase
from api._reports import load_report_data
from api._shared import cookie_value, json_response, verify_payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        requested = query.get("location", [""])[0].strip()
        start = query.get("from", [""])[0]
        end = query.get("to", [""])[0]
        if not requested or len(start) != 10 or len(end) != 10 or start > end:
            json_response(self, {"error": "Choose a location and valid date range."}, 400)
            return
        try:
            data = load_report_data(LarkBase())
            names = sorted(
                {location["name"] for day in data["days"] for location in day["locations"] if location["name"]},
                key=str.casefold,
            )
            matched = next((name for name in names if name.casefold() == requested.casefold()), None)
            if not matched:
                matched = next((name for name in names if requested.casefold() in name.casefold()), None)
            if not matched:
                raise ValueError(f"No location matches {requested}.")
            grouped = {}
            all_dates = set()
            for day in data["days"]:
                if day["status"] != "worked" or not start <= day["date"] <= end:
                    continue
                hours = sum(item["hours"] for item in day["locations"] if item["name"].casefold() == matched.casefold())
                if not hours:
                    continue
                item = grouped.setdefault(day["worker_key"], {"worker_id": day["worker_id"], "worker_name": day["worker_name"], "hours": 0.0, "dates": set()})
                item["hours"] += hours
                item["dates"].add(day["date"])
                all_dates.add(day["date"])
            workers = []
            for item in grouped.values():
                dates = sorted(item.pop("dates"))
                item.update({"hours": round(item["hours"], 2), "days": len(dates), "first_date": dates[0], "last_date": dates[-1]})
                workers.append(item)
            workers.sort(key=lambda item: (-item["hours"], item["worker_name"].casefold()))
            dates = sorted(all_dates)
            json_response(self, {"location": matched, "range": {"from": start, "to": end}, "totals": {"workers": len(workers), "hours": round(sum(item["hours"] for item in workers), 2), "days": len(dates), "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None}, "workers": workers, "cost_centers": []})
        except (ValueError, LarkAPIError) as error:
            status = error.status if isinstance(error, LarkAPIError) else 400
            json_response(self, {"error": str(error)}, status)
