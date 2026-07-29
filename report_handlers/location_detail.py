from __future__ import annotations

from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._reports import aggregate, california_overtime, load_report_data
from api._shared import cookie_value, json_response, verify_payload


def build_worker_site_detail(
    data: dict,
    worker_key: str,
    location_name: str,
    start: date,
    end: date,
) -> dict:
    worker = data["workers"].get(worker_key)
    if not worker:
        raise ValueError("Choose a valid worker.")
    breakdown = california_overtime(
        data["days"], worker_key, start, end, worker["worker_type"],
    )
    days = []
    for work_day in data["days"]:
        if (
            work_day["worker_key"] != worker_key
            or work_day["status"] != "worked"
            or not start.isoformat() <= work_day["date"] <= end.isoformat()
        ):
            continue
        site_entries = [
            item for item in work_day["locations"]
            if item["name"].casefold() == location_name.casefold()
        ]
        site_hours = sum(float(item.get("hours") or 0) for item in site_entries)
        day_hours = max(float(work_day.get("total_hours") or 0), 0.0)
        if not site_hours or not day_hours:
            continue
        share = site_hours / day_hours
        part = breakdown.get(work_day["date"], {
            "regular_hours": day_hours,
            "overtime_hours": 0,
            "doubletime_hours": 0,
            "weighted_hours": day_hours,
        })
        centers: dict[str, dict] = {}
        for entry in site_entries:
            entry_centers = entry.get("cost_centers") or []
            for center in entry_centers:
                center_id = str(center.get("id") or "")
                current = centers.setdefault(
                    center_id,
                    {"id": center_id, "name": center.get("name") or "", "hours": 0.0},
                )
                current["hours"] += float(entry.get("hours") or 0) / max(len(entry_centers), 1)
        weighted_hours = float(part["weighted_hours"]) * share
        days.append({
            "date": work_day["date"],
            "site_hours": round(site_hours, 2),
            "regular_hours": round(float(part["regular_hours"]) * share, 2),
            "overtime_hours": round(float(part["overtime_hours"]) * share, 2),
            "doubletime_hours": round(float(part["doubletime_hours"]) * share, 2),
            "weighted_hours": round(weighted_hours, 2),
            "estimated_cost": round(weighted_hours * float(worker.get("daily_rate") or 0) / 8.0, 2),
            "cost_centers": [
                {**center, "hours": round(center["hours"], 2)}
                for center in centers.values()
            ],
        })
    days.sort(key=lambda item: item["date"])
    return {
        "worker": worker,
        "location": location_name,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "totals": {
            "days": len(days),
            "hours": round(sum(item["site_hours"] for item in days), 2),
            "regular_hours": round(sum(item["regular_hours"] for item in days), 2),
            "overtime_hours": round(sum(item["overtime_hours"] for item in days), 2),
            "doubletime_hours": round(sum(item["doubletime_hours"] for item in days), 2),
            "weighted_hours": round(sum(item["weighted_hours"] for item in days), 2),
            "estimated_cost": round(sum(item["estimated_cost"] for item in days), 2),
        },
        "days": days,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        requested = query.get("location", [""])[0].strip()
        worker_id = query.get("worker_id", [""])[0].strip()
        start = query.get("from", [""])[0]
        end = query.get("to", [""])[0]
        if not requested or len(start) != 10 or len(end) != 10 or start > end:
            json_response(self, {"error": "Choose a site and valid date range."}, 400)
            return
        if worker_id and not worker_id.isdigit():
            json_response(self, {"error": "Choose a valid worker."}, 400)
            return
        try:
            requested_start = date.fromisoformat(start)
            requested_end = date.fromisoformat(end)
            # Include the surrounding week so California weekly overtime is
            # reflected even when the selected location range starts mid-week.
            query_start = requested_start - timedelta(days=requested_start.weekday())
            query_end = requested_end + timedelta(days=6 - requested_end.weekday())
            data = load_report_data(
                DataStore(), query_start, query_end,
                worker_key=worker_id,
                location=requested,
            )
            names = sorted(
                {location["name"] for day in data["days"] for location in day["locations"] if location["name"]},
                key=str.casefold,
            )
            matched = next((name for name in names if name.casefold() == requested.casefold()), None)
            if not matched:
                matched = next((name for name in names if requested.casefold() in name.casefold()), None)
            if not matched:
                raise ValueError(f"No site matches {requested}.")
            if worker_id:
                json_response(
                    self,
                    build_worker_site_detail(
                        data, worker_id, matched, requested_start, requested_end,
                    ),
                )
                return
            grouped = {}
            all_dates = set()
            for day in data["days"]:
                if day["status"] != "worked" or not start <= day["date"] <= end:
                    continue
                hours = sum(item["hours"] for item in day["locations"] if item["name"].casefold() == matched.casefold())
                if not hours:
                    continue
                item = grouped.setdefault(day["worker_key"], {"worker_id": day["worker_id"], "worker_key": day["worker_key"], "worker_name": day["worker_name"], "hours": 0.0, "dates": set()})
                item["hours"] += hours
                item["dates"].add(day["date"])
                all_dates.add(day["date"])
            workers = []
            for item in grouped.values():
                dates = sorted(item.pop("dates"))
                worker_key = item.pop("worker_key")
                worker = data["workers"].get(worker_key, {})
                rate = float(worker.get("daily_rate") or 0)
                worker_type = str(worker.get("worker_type") or "1099")
                weighted_by_day = california_overtime(
                    data["days"], worker.get("key", ""),
                    requested_start, requested_end, worker_type,
                )
                estimated_cost = 0.0
                for work_day in data["days"]:
                    if work_day["worker_key"] != worker_key or work_day["date"] not in dates:
                        continue
                    actual_day_hours = max(float(work_day.get("total_hours") or 0), 0.0)
                    location_hours = sum(float(location.get("hours") or 0) for location in work_day["locations"] if location["name"].casefold() == matched.casefold())
                    if not location_hours or not actual_day_hours:
                        continue
                    weighted_hours = float(weighted_by_day.get(work_day["date"], {}).get("weighted_hours", actual_day_hours))
                    estimated_cost += location_hours * (weighted_hours / actual_day_hours) * rate / 8.0
                item.update({"hours": round(item["hours"], 2), "days": len(dates), "first_date": dates[0], "last_date": dates[-1], "worker_type": worker_type, "daily_rate": round(rate, 2), "estimated_cost": round(estimated_cost, 2)})
                workers.append(item)
            workers.sort(key=lambda item: (-item["hours"], item["worker_name"].casefold()))
            dates = sorted(all_dates)
            selected_days = [day for day in data["days"] if start <= day["date"] <= end]
            json_response(self, {"location": matched, "range": {"from": start, "to": end}, "totals": {"workers": len(workers), "hours": round(sum(item["hours"] for item in workers), 2), "estimated_cost": round(sum(item["estimated_cost"] for item in workers), 2), "days": len(dates), "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None}, "workers": workers, "cost_centers": aggregate(selected_days, "cost_centers")})
        except (ValueError, LarkAPIError) as error:
            status = error.status if isinstance(error, LarkAPIError) else 400
            json_response(self, {"error": str(error)}, status)
