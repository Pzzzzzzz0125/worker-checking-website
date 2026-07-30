from __future__ import annotations

from datetime import timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._reports import aggregate, california_overtime, load_report_data, report_period
from api._shared import cookie_value, json_response, verify_payload


def aggregate_with_estimated_cost(
    days: list[dict], field_name: str, daily_rate: float,
) -> list[dict]:
    rows = aggregate(days, field_name)
    costs: dict[str, float] = {}
    regular_hours: dict[str, float] = {}
    weighted_hours: dict[str, float] = {}
    missing = {
        "hours": 0.0,
        "regular_hours": 0.0,
        "weighted_hours": 0.0,
        "estimated_cost": 0.0,
        "dates": set(),
    }
    for day in days:
        actual_hours = max(float(day.get("total_hours") or 0), 0.0)
        if not actual_hours:
            missing["estimated_cost"] += float(day.get("extra_pay") or 0)
            if day.get("extra_pay"):
                missing["dates"].add(day["date"])
            continue
        labor_cost = float(day.get("weighted_hours") or actual_hours) * daily_rate / 8.0
        represented_hours = 0.0
        for item in day[field_name]:
            item_hours = max(float(item.get("hours") or 0), 0.0)
            key = item.get("id") or item.get("name", "").casefold()
            if key:
                represented_hours += item_hours
                share = item_hours / actual_hours
                costs[key] = costs.get(key, 0.0) + (
                    labor_cost * share
                )
                regular_hours[key] = regular_hours.get(key, 0.0) + (
                    float(day.get("regular_hours") or 0) * share
                )
                weighted_hours[key] = weighted_hours.get(key, 0.0) + (
                    float(day.get("weighted_hours") or actual_hours) * share
                )
        missing_hours = max(actual_hours - represented_hours, 0.0)
        missing_share = missing_hours / actual_hours
        missing["hours"] += missing_hours
        missing["regular_hours"] += float(day.get("regular_hours") or 0) * missing_share
        missing["weighted_hours"] += float(
            day.get("weighted_hours") or actual_hours
        ) * missing_share
        missing["estimated_cost"] += labor_cost * missing_share
        missing["estimated_cost"] += float(day.get("extra_pay") or 0)
        if missing_hours or day.get("extra_pay"):
            missing["dates"].add(day["date"])
    for row in rows:
        key = row.get("id") or row.get("name", "").casefold()
        row["regular_hours"] = round(regular_hours.get(key, 0.0), 2)
        row["weighted_hours"] = round(weighted_hours.get(key, 0.0), 2)
        row["estimated_cost"] = round(costs.get(key, 0.0), 2)
    if missing["hours"] or missing["estimated_cost"]:
        rows.append({
            "id": "",
            "name": "--",
            "hours": round(missing["hours"], 2),
            "regular_hours": round(missing["regular_hours"], 2),
            "weighted_hours": round(missing["weighted_hours"], 2),
            "estimated_cost": round(missing["estimated_cost"], 2),
            "days": len(missing["dates"]),
            "worker_count": 1,
            "first_date": min(missing["dates"]) if missing["dates"] else None,
            "last_date": max(missing["dates"]) if missing["dates"] else None,
        })
    return rows


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60):
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        query = parse_qs(urlparse(self.path).query)
        worker_id = query.get("worker_id", [""])[0]
        try:
            start, end = report_period(query)
            if not worker_id.isdigit():
                raise ValueError("Choose a valid worker.")
            query_start = start - timedelta(days=start.weekday())
            query_end = end + timedelta(days=6 - end.weekday())
            data = load_report_data(
                DataStore(), query_start, query_end, worker_key=worker_id,
                check_period_start=start,
            )
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
                    "period": {"from": start.isoformat(), "to": end.isoformat()},
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
                    "locations": aggregate_with_estimated_cost(
                        selected, "locations", worker["daily_rate"],
                    ),
                    "cost_centers": aggregate_with_estimated_cost(
                        selected, "cost_centers", worker["daily_rate"],
                    ),
                },
            )
        except (ValueError, LarkAPIError) as error:
            status = error.status if isinstance(error, LarkAPIError) else 400
            json_response(self, {"error": str(error)}, status)
