from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from api._lark import LarkAPIError, paged_items, tenant_access_token


REQUIRED_TABLES = {
    "Workers",
    "Work Days",
    "Location Entries",
    "Cost Centers",
    "Payroll Checks",
    "Audit Log",
}


class LarkBase:
    def __init__(self) -> None:
        self.token = tenant_access_token()
        self.app_token = os.environ.get("LARK_BASE_APP_TOKEN", "").strip()
        if not self.app_token:
            raise LarkAPIError("LARK_BASE_APP_TOKEN is not configured.", status=503)
        self._table_ids: dict[str, str] | None = None

    def table_ids(self) -> dict[str, str]:
        if self._table_ids is None:
            path = f"/bitable/v1/apps/{quote(self.app_token, safe='')}/tables"
            tables = paged_items(path, token=self.token)
            self._table_ids = {
                str(item.get("name") or ""): str(item.get("table_id") or "")
                for item in tables
                if item.get("name") and item.get("table_id")
            }
        return self._table_ids

    def missing_tables(self) -> list[str]:
        return sorted(REQUIRED_TABLES - self.table_ids().keys())

    def records(self, table_name: str) -> list[dict]:
        table_id = self.table_ids().get(table_name, "")
        if not table_id:
            raise LarkAPIError(f"The Lark Base table {table_name!r} does not exist.", status=503)
        path = (
            f"/bitable/v1/apps/{quote(self.app_token, safe='')}/tables/"
            f"{quote(table_id, safe='')}/records"
        )
        return paged_items(path, token=self.token)


def field(record: dict, name: str):
    fields = record.get("fields")
    return fields.get(name) if isinstance(fields, dict) else None


def text_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "name", "value", "link"):
            if value.get(key) is not None:
                return text_value(value[key])
        return ""
    if isinstance(value, list):
        return "".join(text_value(item) for item in value).strip()
    return str(value).strip()


def number_value(value, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        text = text_value(value).replace(",", "").strip()
        try:
            return float(text)
        except ValueError:
            return default


def bool_value(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = text_value(value).casefold()
    if text in {"true", "yes", "1", "active", "checked"}:
        return True
    if text in {"false", "no", "0", "inactive", "unchecked"}:
        return False
    return default


def date_value(value) -> str:
    if isinstance(value, (int, float)):
        timezone = ZoneInfo(os.environ.get("APP_TIME_ZONE", "America/Los_Angeles"))
        return datetime.fromtimestamp(float(value) / 1000, timezone).date().isoformat()
    text = text_value(value)
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    return ""


def worker_id(value, fallback: int = 0) -> int:
    text = text_value(value)
    try:
        return int(float(text))
    except ValueError:
        return fallback
