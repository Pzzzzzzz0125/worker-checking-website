from __future__ import annotations

import json
import hmac
import os
import re
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from urllib.parse import parse_qs, quote, unquote, urlparse
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from api._data_store import DataStore
from api._lark import LarkAPIError, lark_api, tenant_access_token
from api._lark_base import bool_value, field, text_value
from api._lark_drive import download_file
from api._permissions import is_super_admin
from api._shared import json_response
from report_handlers.settings import current_session
from xlsx_workbook import normalize_sheet_name, read_cost_centers


TABLE = "Cost Centers"
KEY_FIELD = "Cost Center ID"


def cost_code_source(value: str | None = None) -> dict:
    """Turn a separate Lark Sheet/file link into a Drive download item."""
    raw = (value if value is not None else os.environ.get("LARK_COST_CODE_SOURCE_URL", "")).strip()
    if not raw:
        raise LarkAPIError("LARK_COST_CODE_SOURCE_URL is not configured.", status=503)
    parsed = urlparse(raw)
    path = unquote(parsed.path if parsed.scheme else raw).strip("/")
    match = re.search(r"(?:^|/)(sheets|file|wiki)/([^/?#]+)", path, re.IGNORECASE)
    if not match:
        raise LarkAPIError(
            "The Cost Code source must be a Lark /wiki/, /sheets/, or /file/ link.", status=503,
        )
    link_type = match.group(1).casefold()
    source_type = "sheet" if link_type == "sheets" else link_type
    sheet_id = parse_qs(parsed.query).get("sheet", [""])[0] if parsed.scheme else ""
    return {
        "token": match.group(2), "type": source_type,
        "name": "Connected Cost Code source", "sheet_id": sheet_id,
    }


def resolve_source(item: dict, token: str) -> dict:
    """Resolve a Wiki node to the actual Sheet/file object used by Drive."""
    if item.get("type") != "wiki":
        return item
    payload = lark_api(
        "GET", "/wiki/v2/spaces/get_node", token=token,
        query={"token": str(item.get("token") or "")},
    )
    node = (payload.get("data") or {}).get("node") or {}
    obj_token = str(node.get("obj_token") or "").strip()
    obj_type = str(node.get("obj_type") or "").strip().casefold()
    if not obj_token or obj_type not in {"sheet", "file"}:
        raise LarkAPIError(
            f"The connected Wiki node must contain a Sheet or Excel file, not {obj_type or 'an unknown type'}.",
            status=422,
        )
    return {
        "token": obj_token, "type": obj_type,
        "name": "Connected Wiki Cost Code source",
        "sheet_id": str(item.get("sheet_id") or ""),
    }


def read_sheet_cost_centers(item: dict, token: str) -> list[dict[str, str]]:
    sheet_id = str(item.get("sheet_id") or "").strip()
    if not sheet_id:
        return []
    cell_range = quote(f"{sheet_id}!B1:C5000", safe="")
    spreadsheet_token = quote(str(item.get("token") or ""), safe="")
    payload = lark_api(
        "GET",
        f"/sheets/v2/spreadsheets/{spreadsheet_token}/values/{cell_range}",
        token=token,
    )
    values = (((payload.get("data") or {}).get("valueRange") or {}).get("values") or [])
    if not isinstance(values, list) or not values:
        return []
    header = values[0] if isinstance(values[0], list) else []
    if (
        normalize_sheet_name(header[0] if len(header) > 0 else "").casefold() != "id"
        or normalize_sheet_name(header[1] if len(header) > 1 else "").casefold() != "name"
    ):
        return []
    centers: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in values[1:]:
        if not isinstance(raw, list):
            continue
        center_id = normalize_sheet_name(raw[0] if len(raw) > 0 else "")
        center_name = normalize_sheet_name(raw[1] if len(raw) > 1 else "")
        if center_id and center_name and center_id not in seen:
            centers.append({"id": center_id, "name": center_name})
            seen.add(center_id)
    return centers


def _admin(handler: BaseHTTPRequestHandler) -> dict | None:
    session = current_session(handler)
    if not session:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return None
    if not is_super_admin(session):
        json_response(handler, {"error": "Only a Super Admin can update Cost Codes."}, 403)
        return None
    return session


def _source_rows() -> tuple[dict, list[dict]]:
    token = tenant_access_token()
    item = resolve_source(cost_code_source(), token)
    parsed = read_sheet_cost_centers(item, token) if item.get("type") == "sheet" else []
    if not parsed:
        workbook = download_file(item, token)
        parsed = read_cost_centers(BytesIO(workbook))
    if not parsed:
        raise LarkAPIError(
            "No Cost Codes were found. The source must have ID in column B and Name in column C.",
            status=422,
        )
    return item, [
        {
            KEY_FIELD: center["id"],
            "Name": center["name"],
            "Active": True,
            "Display Order": index,
        }
        for index, center in enumerate(parsed, start=1)
    ]


def _number(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def changed_rows(source_rows: list[dict], existing_records: list[dict]) -> tuple[list[dict], dict]:
    existing = {
        text_value(field(record, KEY_FIELD)): record
        for record in existing_records
        if text_value(field(record, KEY_FIELD))
    }
    additions = 0
    updates = 0
    changed: list[dict] = []
    for row in source_rows:
        key = text_value(row.get(KEY_FIELD))
        current = existing.get(key)
        if current is None:
            additions += 1
            changed.append(row)
            continue
        if (
            text_value(field(current, "Name")) != text_value(row.get("Name"))
            or not bool_value(field(current, "Active"), True)
            or _number(field(current, "Display Order")) != _number(row.get("Display Order"))
        ):
            updates += 1
            changed.append(row)
    return changed, {
        "source_rows": len(source_rows),
        "database_rows": len(existing),
        "added": additions,
        "updated": updates,
        "unchanged": len(source_rows) - additions - updates,
    }


def cron_authorized(authorization: str, secret: str | None = None) -> bool:
    expected = (secret if secret is not None else os.environ.get("CRON_SECRET", "")).strip()
    supplied = str(authorization or "")
    return bool(expected) and hmac.compare_digest(supplied, f"Bearer {expected}")


def sync_cost_codes(actor: str) -> dict:
    base = DataStore()
    item, source_rows = _source_rows()
    existing = base.records(TABLE, cache_seconds=0)
    rows, counts = changed_rows(source_rows, existing)
    result = {"created": 0, "updated": 0}
    if rows:
        result = base.batch_set_by_key(
            TABLE, KEY_FIELD, rows, existing_records=existing,
        )
    return {
        "configured": True,
        "source_type": item["type"],
        "database_rows": counts["database_rows"] + counts["added"],
        "counts": counts,
        "result": result,
        "actor": actor,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not _admin(self):
            return
        try:
            base = DataStore()
            current = base.records(TABLE, cache_seconds=0)
            source = cost_code_source()
            json_response(self, {
                "configured": True,
                "source_type": source["type"],
                "database_rows": len(current),
            })
        except LarkAPIError as error:
            if error.status == 503 and "not configured" in str(error):
                json_response(self, {
                    "configured": False,
                    "source_type": "",
                    "database_rows": 0,
                    "message": str(error),
                })
                return
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)

    def do_CRON(self) -> None:
        if not cron_authorized(self.headers.get("Authorization", "")):
            json_response(self, {"error": "Unauthorized scheduled sync."}, 401)
            return
        try:
            json_response(self, sync_cost_codes("Vercel daily cron"))
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
        except (BadZipFile, ParseError, KeyError, ValueError, OSError) as error:
            json_response(self, {"error": f"Could not read the Cost Code workbook: {error}"}, 422)

    def do_POST(self) -> None:
        session = _admin(self)
        if not session:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict) or body.get("action") != "sync":
                raise ValueError("Choose the Cost Code sync action.")
            json_response(self, sync_cost_codes(
                session.get("name") or session.get("sub") or "Lark administrator",
            ))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": str(error)}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
        except (BadZipFile, ParseError, KeyError, OSError) as error:
            json_response(self, {"error": f"Could not read the Cost Code workbook: {error}"}, 422)
