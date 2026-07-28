from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

from api._lark import LarkAPIError, lark_api, paged_items, tenant_access_token
from api._shared import cookie_value, json_response, verify_payload


TEXT = 1
NUMBER = 2
DATE = 5
CHECKBOX = 7


SCHEMA = {
    "Workers": [
        ("Worker Key", TEXT),
        ("Name", TEXT),
        ("Normalized Name", TEXT),
        ("Worker Type", TEXT),
        ("Active", CHECKBOX),
        ("Daily Rate", NUMBER),
        ("Display Order", NUMBER),
        ("Aliases", TEXT),
        ("Notes", TEXT),
    ],
    "Work Days": [
        ("Work Day Key", TEXT),
        ("Worker Key", TEXT),
        ("Worker Name", TEXT),
        ("Work Date", DATE),
        ("Status", TEXT),
        ("Total Hours", NUMBER),
        ("Location Hours Sum", NUMBER),
        ("Total Hours Source", TEXT),
        ("Hours Difference", NUMBER),
        ("Overtime Hours", NUMBER),
        ("Calculated Overtime Hours", NUMBER),
        ("Overtime Source", TEXT),
        ("Override Reason", TEXT),
        ("Override By", TEXT),
        ("Extra Pay", NUMBER),
        ("Start Time", TEXT),
        ("End Time", TEXT),
        ("Notes", TEXT),
        ("Original Text", TEXT),
        ("Source", TEXT),
        ("Confidence", TEXT),
        ("Updated At", DATE),
    ],
    "Location Entries": [
        ("Location Entry Key", TEXT),
        ("Work Day Key", TEXT),
        ("Worker Key", TEXT),
        ("Work Date", DATE),
        ("Location", TEXT),
        ("Cost Center ID", TEXT),
        ("Cost Center Name", TEXT),
        ("Start Time", TEXT),
        ("End Time", TEXT),
        ("Location Hours", NUMBER),
        ("Regular Hours", NUMBER),
        ("Overtime Hours", NUMBER),
        ("Display Order", NUMBER),
    ],
    "Cost Centers": [
        ("Cost Center ID", TEXT),
        ("Name", TEXT),
        ("Active", CHECKBOX),
        ("Display Order", NUMBER),
    ],
    "Payroll Checks": [
        ("Payroll Check Key", TEXT),
        ("Worker Key", TEXT),
        ("Period Start", DATE),
        ("Period End", DATE),
        ("Checked", CHECKBOX),
        ("Checked By", TEXT),
        ("Checked At", DATE),
    ],
    "Audit Log": [
        ("Audit Key", TEXT),
        ("Actor ID", TEXT),
        ("Actor Name", TEXT),
        ("Action", TEXT),
        ("Entity Type", TEXT),
        ("Entity Key", TEXT),
        ("Work Date", DATE),
        ("Old JSON", TEXT),
        ("New JSON", TEXT),
        ("Source", TEXT),
        ("Created At", DATE),
    ],
    "Work Log": [
        ("Entry Key", TEXT),
        ("Work Date", DATE),
        ("Worker Key", TEXT),
        ("Worker Name", TEXT),
        ("Status", TEXT),
        ("Normalized Entry", TEXT),
        ("Total Hours", NUMBER),
        ("Location Hours Sum", NUMBER),
        ("Hours Difference", NUMBER),
        ("Regular Hours", NUMBER),
        ("Overtime Hours", NUMBER),
        ("Calculated Overtime Hours", NUMBER),
        ("Override Reason", TEXT),
        ("Override By", TEXT),
        ("Extra Pay", NUMBER),
        ("Locations", TEXT),
        ("Cost Centers", TEXT),
        ("Notes", TEXT),
        ("Source", TEXT),
        ("Confidence", TEXT),
        ("Updated At", DATE),
    ],
}


def _session(handler: BaseHTTPRequestHandler) -> dict | None:
    return verify_payload(cookie_value(handler, "workforce_session"), 12 * 60 * 60)


def _base_token() -> str:
    token = os.environ.get("LARK_BASE_APP_TOKEN", "").strip()
    if not token:
        raise LarkAPIError("LARK_BASE_APP_TOKEN is not configured.", status=503)
    return token


def _tables(token: str, app_token: str) -> list[dict]:
    return paged_items(
        f"/bitable/v1/apps/{quote(app_token, safe='')}/tables",
        token=token,
    )


def _fields(token: str, app_token: str, table_id: str) -> list[dict]:
    return paged_items(
        f"/bitable/v1/apps/{quote(app_token, safe='')}/tables/{quote(table_id, safe='')}/fields",
        token=token,
    )


def _snapshot(token: str, app_token: str) -> dict:
    metadata = lark_api(
        "GET",
        f"/bitable/v1/apps/{quote(app_token, safe='')}",
        token=token,
    ).get("data", {}).get("app", {})
    tables = _tables(token, app_token)
    result = []
    for table in tables:
        table_id = str(table.get("table_id") or "")
        if not table_id:
            continue
        fields = _fields(token, app_token, table_id)
        result.append(
            {
                "name": table.get("name", ""),
                "table_id": table_id,
                "fields": [
                    {
                        "name": field.get("field_name", ""),
                        "field_id": field.get("field_id", ""),
                        "type": field.get("type"),
                        "primary": bool(field.get("is_primary")),
                    }
                    for field in fields
                ],
            }
        )
    names = {item["name"] for item in result}
    return {
        "base": {
            "name": metadata.get("name", ""),
            "app_token": metadata.get("app_token", app_token),
            "time_zone": metadata.get("time_zone", ""),
        },
        "ready": all(name in names for name in SCHEMA),
        "tables": result,
    }


def _initialize(token: str, app_token: str) -> dict:
    current = {str(item.get("name") or ""): item for item in _tables(token, app_token)}
    created_tables: list[str] = []
    created_fields: list[str] = []
    warnings: list[str] = []

    for table_name, required_fields in SCHEMA.items():
        table = current.get(table_name)
        just_created = table is None
        if just_created:
            payload = lark_api(
                "POST",
                f"/bitable/v1/apps/{quote(app_token, safe='')}/tables",
                token=token,
                body={
                    "table": {
                        "name": table_name,
                        "default_view_name": "All Records",
                        "fields": [
                            {"field_name": field_name, "type": field_type}
                            for field_name, field_type in required_fields
                        ],
                    }
                },
            )
            data = payload.get("data") or {}
            nested_table = data.get("table") if isinstance(data, dict) else None
            if isinstance(nested_table, dict):
                table = nested_table
            else:
                table = {
                    "name": table_name,
                    "table_id": data.get("table_id", "") if isinstance(data, dict) else "",
                }
            if not table.get("table_id"):
                raise LarkAPIError(f"Lark created {table_name} without returning its table ID.")
            current[table_name] = table
            created_tables.append(table_name)

        table_id = str(table.get("table_id") or "")
        fields = _fields(token, app_token, table_id)
        by_name = {str(field.get("field_name") or ""): field for field in fields}

        for field_name, field_type in required_fields:
            existing = by_name.get(field_name)
            if existing:
                if existing.get("type") != field_type:
                    warnings.append(
                        f"{table_name}.{field_name} has type {existing.get('type')}, expected {field_type}."
                    )
                continue
            lark_api(
                "POST",
                f"/bitable/v1/apps/{quote(app_token, safe='')}/tables/{quote(table_id, safe='')}/fields",
                token=token,
                body={"field_name": field_name, "type": field_type},
            )
            created_fields.append(f"{table_name}.{field_name}")

    return {
        "created_tables": created_tables,
        "created_fields": created_fields,
        "warnings": warnings,
        "schema": _snapshot(token, app_token),
    }


class handler(BaseHTTPRequestHandler):
    def _authenticated(self) -> dict | None:
        session = _session(self)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return None
        return session

    def do_GET(self) -> None:
        if not self._authenticated():
            return
        try:
            token = tenant_access_token()
            json_response(self, _snapshot(token, _base_token()))
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)

    def do_POST(self) -> None:
        session = self._authenticated()
        if not session:
            return
        admins = {
            value.strip()
            for value in os.environ.get("LARK_ADMIN_OPEN_IDS", "").split(",")
            if value.strip()
        }
        if not admins:
            json_response(
                self,
                {
                    "error": "LARK_ADMIN_OPEN_IDS is not configured. Copy your ID from /api/auth/me, add it in Vercel, and redeploy."
                },
                503,
            )
            return
        if session.get("sub") not in admins:
            json_response(self, {"error": "Only a configured Lark administrator can initialize the Base."}, 403)
            return
        try:
            token = tenant_access_token()
            json_response(self, _initialize(token, _base_token()))
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
