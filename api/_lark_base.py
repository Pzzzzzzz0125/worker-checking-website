from __future__ import annotations

import os
import json
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from api._lark import LarkAPIError, lark_api, paged_items, tenant_access_token


REQUIRED_TABLES = {
    "Workers",
    "Work Days",
    "Location Entries",
    "Cost Centers",
    "Payroll Checks",
    "Audit Log",
}
_TABLE_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_RECORD_CACHE: dict[tuple[str, str, str, tuple[str, ...]], tuple[float, list[dict]]] = {}


class LarkBase:
    def __init__(self) -> None:
        self.token = tenant_access_token()
        self.app_token = os.environ.get("LARK_BASE_APP_TOKEN", "").strip()
        if not self.app_token:
            raise LarkAPIError("LARK_BASE_APP_TOKEN is not configured.", status=503)
        self._table_ids: dict[str, str] | None = None

    def table_ids(self) -> dict[str, str]:
        if self._table_ids is None:
            cached = _TABLE_CACHE.get(self.app_token)
            if cached and time.monotonic() < cached[0]:
                self._table_ids = dict(cached[1])
                return self._table_ids
            path = f"/bitable/v1/apps/{quote(self.app_token, safe='')}/tables"
            tables = paged_items(path, token=self.token)
            self._table_ids = {
                str(item.get("name") or ""): str(item.get("table_id") or "")
                for item in tables
                if item.get("name") and item.get("table_id")
            }
            _TABLE_CACHE[self.app_token] = (
                time.monotonic() + 300,
                dict(self._table_ids),
            )
        return self._table_ids

    def missing_tables(self) -> list[str]:
        return sorted(REQUIRED_TABLES - self.table_ids().keys())

    def records(
        self,
        table_name: str,
        *,
        filter_formula: str = "",
        field_names: tuple[str, ...] = (),
        cache_seconds: int = 45,
    ) -> list[dict]:
        table_id = self.table_ids().get(table_name, "")
        if not table_id:
            raise LarkAPIError(f"The Lark Base table {table_name!r} does not exist.", status=503)
        cache_key = (self.app_token, table_name, filter_formula, field_names)
        cached = _RECORD_CACHE.get(cache_key)
        if cache_seconds and cached and time.monotonic() < cached[0]:
            return list(cached[1])
        path = (
            f"/bitable/v1/apps/{quote(self.app_token, safe='')}/tables/"
            f"{quote(table_id, safe='')}/records"
        )
        query: dict[str, str | int] = {}
        if filter_formula:
            query["filter"] = filter_formula
        if field_names:
            query["field_names"] = json.dumps(field_names)
        # Base record listing supports up to 500 rows per request. Using that
        # limit reduces a 6,800-row table from about 69 requests to 14.
        records = paged_items(path, token=self.token, page_size=500, query=query)
        if cache_seconds:
            _RECORD_CACHE[cache_key] = (time.monotonic() + cache_seconds, list(records))
        return records

    def invalidate_records(self, table_name: str) -> None:
        for key in list(_RECORD_CACHE):
            if key[0] == self.app_token and key[1] == table_name:
                _RECORD_CACHE.pop(key, None)

    def create_missing(
        self,
        table_name: str,
        key_field: str,
        rows: list[dict],
        *,
        batch_size: int = 500,
    ) -> dict:
        """Create only absent keyed rows so retrying cannot overwrite app edits."""
        table_id = self.table_ids().get(table_name, "")
        if not table_id:
            raise LarkAPIError(f"The Lark Base table {table_name!r} does not exist.", status=503)
        existing: dict[str, dict] = {}
        for record in self.records(table_name):
            key = text_value(field(record, key_field))
            if not key:
                continue
            if key in existing:
                raise LarkAPIError(
                    f"{table_name} contains duplicate {key_field} value {key!r}.",
                    status=409,
                )
            existing[key] = record
        supplied_keys: set[str] = set()
        missing = []
        for row in rows:
            key = text_value(row.get(key_field))
            if not key:
                raise LarkAPIError(f"A {table_name} migration row is missing {key_field}.")
            if key in supplied_keys:
                raise LarkAPIError(
                    f"Migration data contains duplicate {table_name} key {key!r}.",
                    status=409,
                )
            supplied_keys.add(key)
            if key not in existing:
                missing.append(row)
        path = (
            f"/bitable/v1/apps/{quote(self.app_token, safe='')}/tables/"
            f"{quote(table_id, safe='')}/records/batch_create"
        )
        for offset in range(0, len(missing), batch_size):
            batch = missing[offset : offset + batch_size]
            lark_api(
                "POST",
                path,
                token=self.token,
                body={"records": [{"fields": row} for row in batch]},
            )
        if missing:
            self.invalidate_records(table_name)
        return {
            "expected": len(rows),
            "created": len(missing),
            "already_present": len(rows) - len(missing),
        }

    def set_by_key(self, table_name: str, key_field: str, key: str, fields: dict) -> dict:
        """Create or update one keyed record."""
        table_id = self.table_ids().get(table_name, "")
        if not table_id:
            raise LarkAPIError(f"The Lark Base table {table_name!r} does not exist.", status=503)
        matches = [
            record
            for record in self.records(table_name)
            if text_value(field(record, key_field)) == key
        ]
        if len(matches) > 1:
            raise LarkAPIError(f"{table_name} contains duplicate key {key!r}.", status=409)
        base_path = (
            f"/bitable/v1/apps/{quote(self.app_token, safe='')}/tables/"
            f"{quote(table_id, safe='')}/records"
        )
        if matches:
            record_id = str(matches[0].get("record_id") or "")
            lark_api(
                "POST",
                f"{base_path}/batch_update",
                token=self.token,
                body={"records": [{"record_id": record_id, "fields": fields}]},
            )
            self.invalidate_records(table_name)
            return {"created": False, "record_id": record_id}
        payload = lark_api(
            "POST",
            f"{base_path}/batch_create",
            token=self.token,
            body={"records": [{"fields": fields}]},
        )
        created = ((payload.get("data") or {}).get("records") or [{}])[0]
        self.invalidate_records(table_name)
        return {"created": True, "record_id": created.get("record_id", "")}


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


def formula_string(value: str) -> str:
    """Quote a text value safely for a Lark Base filter formula."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def date_range_filter(field_name: str, start: str, end: str) -> str:
    return (
        f'AND(CurrentValue.[{field_name}]>=TODATE({formula_string(start)}),'
        f'CurrentValue.[{field_name}]<=TODATE({formula_string(end)}))'
    )
