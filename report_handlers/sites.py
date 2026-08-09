from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zipfile import BadZipFile, ZipFile

from api._data_store import DataStore
from api._lark import LarkAPIError
from api._lark_base import bool_value, field, text_value
from api._postgres_base import PostgresBase
from api._shared import json_response
from report_handlers.workers import access_status, session
from xlsx_workbook import _shared_strings, sheet_rows, workbook_sheets


TABLE = "Sites"
KEY_FIELD = "Site Key"
SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "site-address-library.csv"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
_POSTGRES_READY = False


def _clean(value, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _clean(value).casefold()).split())


def _site_key(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"speed-construction-site:{_normalized(value)}"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_address(full_address: str) -> dict[str, str]:
    """Split a US-style address without inventing missing components."""
    value = _clean(full_address)
    parts = [_clean(part) for part in value.split(",") if _clean(part)]
    line1 = parts[0] if parts else value
    city = parts[1] if len(parts) >= 2 else ""
    state = ""
    postal_code = ""
    if len(parts) >= 3:
        city = parts[-2]
        match = re.fullmatch(r"([A-Za-z]{2})(?:\s+(\d{5}(?:-\d{4})?))?", parts[-1])
        if match:
            state = match.group(1).upper()
            postal_code = match.group(2) or ""
            line1 = ", ".join(parts[:-2])
        else:
            line1 = parts[0]
    return {
        "address_line_1": line1,
        "city": city,
        "state": state,
        "zip_code": postal_code,
    }


def site_profile(record: dict) -> dict:
    values = record.get("fields") or {}
    return {
        "site_key": text_value(values.get("Site Key")),
        "name": text_value(values.get("Name")),
        "full_address": text_value(values.get("Full Address")),
        "address_line_1": text_value(values.get("Address Line 1")),
        "city": text_value(values.get("City")),
        "state": text_value(values.get("State")),
        "zip_code": text_value(values.get("ZIP Code")),
        "aliases": text_value(values.get("Aliases")),
        "default_cost_code_ids": text_value(values.get("Default Cost Code IDs")),
        "active": bool_value(values.get("Active"), True),
        "verified": bool_value(values.get("Verified"), False),
        "source": text_value(values.get("Source")),
        "notes": text_value(values.get("Notes")),
        "updated_at": text_value(values.get("Updated At")),
        "record_id": str(record.get("record_id") or ""),
    }


def _ready_store(base=None):
    global _POSTGRES_READY
    base = base or DataStore()
    if isinstance(base, PostgresBase):
        if not _POSTGRES_READY:
            base.ensure_schema()
            _POSTGRES_READY = True
    elif not hasattr(base, "table_ids") or not base.table_ids().get(TABLE):
        raise LarkAPIError(
            "The Lark Base Sites table is missing. Run Lark Base setup once as an administrator.",
            status=503,
        )
    return base


def list_sites(base, *, seed_if_empty: bool = False) -> list[dict]:
    base = _ready_store(base)
    records = base.records(TABLE, cache_seconds=0)
    if seed_if_empty and not records and SEED_FILE.exists():
        addresses = [
            _clean(line)
            for line in SEED_FILE.read_text(encoding="utf-8-sig").splitlines()[1:]
            if _clean(line)
        ]
        import_sites(base, [{"full_address": value} for value in addresses], source="Address(1).xlsx")
        records = base.records(TABLE, cache_seconds=0)
    sites = [site_profile(record) for record in records]
    return sorted(
        [site for site in sites if site["site_key"] and site["name"]],
        key=lambda site: (not site["active"], site["name"].casefold()),
    )


def active_site_names(base, *, seed_if_empty: bool = False) -> list[str]:
    return [site["name"] for site in list_sites(base, seed_if_empty=seed_if_empty) if site["active"]]


def _site_fields(body: dict, key: str, *, source: str = "app") -> dict:
    full_address = _clean(body.get("full_address") or body.get("name"), 500)
    name = _clean(body.get("name") or full_address, 500)
    parsed = split_address(full_address)
    address_line_1 = _clean(body.get("address_line_1") or parsed["address_line_1"], 240)
    city = _clean(body.get("city") or parsed["city"], 120)
    state = _clean(body.get("state") or parsed["state"], 40).upper()
    zip_code = _clean(body.get("zip_code") or parsed["zip_code"], 20)
    if not name:
        raise ValueError("Site name or full address is required.")
    if len(state) > 2:
        raise ValueError("State should use its two-letter abbreviation.")
    if zip_code and not re.fullmatch(r"\d{5}(?:-\d{4})?", zip_code):
        raise ValueError("ZIP Code must use 12345 or 12345-6789 format.")
    aliases = "; ".join(
        dict.fromkeys(
            _clean(value, 240)
            for value in re.split(r"[;\n]+", str(body.get("aliases") or ""))
            if _clean(value, 240)
        )
    )
    default_codes = ";".join(
        dict.fromkeys(
            _clean(value, 120)
            for value in re.split(r"[;,\n]+", str(body.get("default_cost_code_ids") or ""))
            if _clean(value, 120)
        )
    )
    return {
        "Site Key": key,
        "Name": name,
        "Full Address": full_address,
        "Address Line 1": address_line_1,
        "City": city,
        "State": state,
        "ZIP Code": zip_code,
        "Aliases": aliases,
        "Default Cost Code IDs": default_codes,
        "Active": bool(body.get("active", True)),
        "Verified": bool(body.get("verified", bool(full_address and city))),
        "Source": _clean(body.get("source") or source, 120),
        "Notes": _clean(body.get("notes"), 2000),
        "Updated At": _now(),
    }


def _lookup(sites: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for site in sites:
        candidates = [site["name"], site["full_address"], site["address_line_1"]]
        candidates.extend(re.split(r"[;\n]+", site["aliases"]))
        for value in candidates:
            normalized = _normalized(value)
            if normalized:
                result.setdefault(normalized, site)
    return result


def save_site(base, body: dict) -> dict:
    base = _ready_store(base)
    sites = list_sites(base)
    supplied_key = _clean(body.get("site_key"), 120)
    existing = {site["site_key"]: site for site in sites}
    if supplied_key and supplied_key not in existing:
        raise ValueError("Choose a valid Site record.")
    name = _clean(body.get("name") or body.get("full_address"), 500)
    key = supplied_key or _site_key(name)
    fields = _site_fields(body, key)
    normalized_name = _normalized(fields["Name"])
    duplicate = next(
        (
            site for site in sites
            if site["site_key"] != key
            and normalized_name in {
                _normalized(site["name"]),
                _normalized(site["full_address"]),
            }
        ),
        None,
    )
    if duplicate:
        raise ValueError(f"This Site already exists as {duplicate['name']}.")
    base.set_by_key(TABLE, KEY_FIELD, key, fields)
    return site_profile({"fields": fields})


def archive_site(base, body: dict, active: bool) -> dict:
    key = _clean(body.get("site_key"), 120)
    existing = {site["site_key"]: site for site in list_sites(base)}
    site = existing.get(key)
    if not site:
        raise ValueError("Choose a valid Site record.")
    site["active"] = active
    saved = save_site(base, site)
    return {"site": saved, "archived": not active, "restored": active}


HEADER_ALIASES = {
    "site key": "site_key",
    "site": "name",
    "site name": "name",
    "name": "name",
    "canonical site": "name",
    "full address": "full_address",
    "address": "full_address",
    "address line 1": "address_line_1",
    "street address": "address_line_1",
    "city": "city",
    "state": "state",
    "zip": "zip_code",
    "zip code": "zip_code",
    "postal code": "zip_code",
    "aliases": "aliases",
    "default cost codes": "default_cost_code_ids",
    "default cost code ids": "default_cost_code_ids",
    "notes": "notes",
    "active": "active",
    "verified": "verified",
}


def _truthy(value: str, default: bool) -> bool:
    cleaned = _clean(value).casefold()
    if not cleaned:
        return default
    return cleaned in {"1", "true", "yes", "y", "active", "verified"}


def _grid_sites(rows: list[list[str]]) -> list[dict]:
    rows = [[_clean(cell) for cell in row] for row in rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return []
    header_map = {
        index: HEADER_ALIASES[_normalized(value)]
        for index, value in enumerate(rows[0])
        if _normalized(value) in HEADER_ALIASES
    }
    output: list[dict] = []
    if header_map:
        for row in rows[1:]:
            item = {
                target: row[index] if index < len(row) else ""
                for index, target in header_map.items()
            }
            if set(header_map.values()) == {"full_address"} and len(row) > 1:
                # Be forgiving when a one-column address CSV was saved without
                # quoting commas inside the address value.
                item["full_address"] = ", ".join(value for value in row if value)
            if item.get("name") or item.get("full_address") or item.get("address_line_1"):
                item["active"] = _truthy(str(item.get("active") or ""), True)
                item["verified"] = _truthy(str(item.get("verified") or ""), True)
                output.append(item)
        return output
    for row in rows:
        candidates = [value for value in row if value]
        if not candidates:
            continue
        address = max(candidates, key=lambda value: (value.count(","), len(value)))
        if address:
            output.append({"full_address": address, "active": True, "verified": True})
    return output


def parse_site_file(payload: bytes, filename: str = "", content_type: str = "") -> list[dict]:
    if not payload:
        raise ValueError("Choose a non-empty XLSX or CSV address file.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError("The address file is larger than 8 MB.")
    if payload.startswith(b"PK") or filename.casefold().endswith(".xlsx"):
        try:
            with ZipFile(io.BytesIO(payload)) as archive:
                shared = _shared_strings(archive)
                grids = []
                for _, path in workbook_sheets(archive):
                    sheet = sheet_rows(archive, path, shared)
                    width = max((max(row, default=0) for row in sheet), default=0)
                    grids.extend(
                        [[row.get(column, "") for column in range(1, width + 1)] for row in sheet]
                    )
                return _grid_sites(grids)
        except (BadZipFile, KeyError, ValueError) as error:
            raise ValueError(f"The XLSX address file could not be read: {error}") from None
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV address files must use UTF-8 encoding.") from None
    return _grid_sites(list(csv.reader(io.StringIO(text))))


def import_sites(base, incoming: list[dict], *, source: str, replace: bool = False) -> dict:
    base = _ready_store(base)
    existing = list_sites(base)
    lookup = _lookup(existing)
    rows: dict[str, dict] = {}
    imported_keys: set[str] = set()
    created = 0
    updated = 0
    duplicates = 0
    for raw in incoming:
        candidate_name = _clean(raw.get("name") or raw.get("full_address") or raw.get("address_line_1"), 500)
        if not candidate_name:
            continue
        normalized = _normalized(candidate_name)
        match = lookup.get(normalized)
        key = (match or {}).get("site_key") or _clean(raw.get("site_key"), 120) or _site_key(candidate_name)
        if key in imported_keys:
            duplicates += 1
            continue
        imported_keys.add(key)
        combined = {**(match or {}), **raw, "site_key": key, "source": source}
        fields = _site_fields(combined, key, source=source)
        rows[key] = fields
        created += int(match is None)
        updated += int(match is not None)
    archived = 0
    if replace:
        for site in existing:
            if site["active"] and site["site_key"] not in imported_keys:
                site["active"] = False
                rows[site["site_key"]] = _site_fields(site, site["site_key"], source=site["source"] or "app")
                archived += 1
    if rows:
        base.batch_set_by_key(TABLE, KEY_FIELD, list(rows.values()))
    return {
        "parsed": len(incoming),
        "created": created,
        "updated": updated,
        "duplicates_skipped": duplicates,
        "archived": archived,
        "active": sum(site["active"] for site in list_sites(base)),
    }


def extract_history_sites(base) -> dict:
    base = _ready_store(base)
    sites = list_sites(base, seed_if_empty=True)
    known = _lookup(sites)
    locations = sorted(
        {
            text_value(field(record, "Location"))
            for record in base.records("Location Entries", field_names=("Location",), cache_seconds=0)
            if text_value(field(record, "Location"))
        },
        key=str.casefold,
    )
    drafts = []
    for location in locations:
        normalized = _normalized(location)
        if normalized in known:
            continue
        # A legacy short form is considered covered only when it uniquely
        # matches the beginning of one formal street address.
        matches = [
            site for site in sites
            if _normalized(site["address_line_1"]).startswith(f"{normalized} ")
        ]
        if len(matches) == 1:
            continue
        drafts.append({
            "name": location,
            "full_address": location,
            "active": False,
            "verified": False,
            "source": "work-entry extraction",
            "notes": "Extracted from historical entries. Formalize and activate before use.",
        })
    result = import_sites(base, drafts, source="work-entry extraction") if drafts else {
        "parsed": 0, "created": 0, "updated": 0, "duplicates_skipped": 0, "archived": 0,
        "active": sum(site["active"] for site in sites),
    }
    return {**result, "history_locations": len(locations)}


def _action(handler: BaseHTTPRequestHandler) -> str:
    return parse_qs(urlparse(handler.path).query).get("action", [""])[0]


def _authorized(handler: BaseHTTPRequestHandler) -> tuple[dict, dict] | None:
    current = session(handler)
    if not current:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return None
    access = access_status(handler, current)
    if not access["authorized"]:
        json_response(
            handler,
            {"error": "Site Management requires administrator access.", "code": "worker_admin_required", **access},
            403,
        )
        return None
    return current, access


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not _authorized(self):
            return
        try:
            sites = list_sites(DataStore(), seed_if_empty=True)
            json_response(self, {
                "sites": sites,
                "totals": {
                    "sites": len(sites),
                    "active": sum(site["active"] for site in sites),
                    "archived": sum(not site["active"] for site in sites),
                    "verified": sum(site["verified"] for site in sites),
                    "needs_review": sum(not site["verified"] for site in sites),
                },
            })
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)

    def do_POST(self) -> None:
        if not _authorized(self):
            return
        try:
            selected_action = _action(self)
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_UPLOAD_BYTES:
                raise ValueError("The address file is larger than 8 MB.")
            payload = self.rfile.read(length)
            base = DataStore()
            if selected_action == "sites_import":
                filename = self.headers.get("X-Filename", "")
                parsed = parse_site_file(payload, filename, self.headers.get("Content-Type", ""))
                if not parsed:
                    raise ValueError("No Site addresses were found in this file.")
                replace = parse_qs(urlparse(self.path).query).get("replace", [""])[0].casefold() in {"1", "true", "yes"}
                json_response(self, import_sites(base, parsed, source=filename or "address file", replace=replace))
                return
            body = json.loads(payload or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            if selected_action == "site_delete":
                json_response(self, archive_site(base, body, False))
                return
            if selected_action == "site_restore":
                json_response(self, archive_site(base, body, True))
                return
            if selected_action == "sites_extract":
                json_response(self, extract_history_sites(base))
                return
            json_response(self, {"saved": True, "site": save_site(base, body)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid Site data: {error}"}, 400)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
