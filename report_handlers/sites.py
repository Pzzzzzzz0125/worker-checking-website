from __future__ import annotations

import csv
import io
import json
import re
import uuid
from collections import Counter, defaultdict
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
    return [
        site["name"]
        for site in list_sites(base, seed_if_empty=seed_if_empty)
        if site["active"] and site["verified"]
    ]


def _legacy_candidates(value: str) -> list[str]:
    """Return possible Site text while treating '=' as legacy punctuation.

    Historical cells sometimes ended with ``=`` (for example
    ``1073 Crosswind =``).  The marker is not a separate Site and must not
    cause the work hours to disappear.  If text exists on both sides, both
    sides are considered and the result is accepted only when it is unique.
    """
    raw = _clean(value)
    candidates = [raw]
    candidates.extend(_clean(part) for part in re.split(r"=+", raw))
    without_equals = _clean(re.sub(r"=+", " ", raw))
    candidates.append(without_equals)
    return list(dict.fromkeys(item for item in candidates if item))


def _leading_number(value: str) -> str:
    match = re.match(r"^\s*(\d+)", _clean(value))
    return match.group(1) if match else ""


_STREET_WORDS = {
    "ave", "avenue", "blvd", "boulevard", "cir", "circle", "ct", "court",
    "dr", "drive", "e", "east", "hwy", "highway", "ln", "lane", "n",
    "north", "pkwy", "parkway", "pl", "place", "rd", "road", "s", "south",
    "st", "street", "ter", "terrace", "w", "way", "west",
}


def _street_tokens(value: str) -> set[str]:
    tokens = _normalized(value).split()
    if tokens and tokens[0].isdigit():
        tokens = tokens[1:]
    return {token for token in tokens if token not in _STREET_WORDS}


class SiteResolver:
    """Resolve legacy Site labels to verified canonical Site records."""

    def __init__(self, sites: list[dict]):
        self.sites = [
            site for site in sites
            if site.get("active") and site.get("verified") and site.get("name")
        ]
        exact: dict[str, list[dict]] = defaultdict(list)
        numbers: dict[str, list[dict]] = defaultdict(list)
        for site in self.sites:
            candidates = [site.get("name"), site.get("full_address"), site.get("address_line_1")]
            candidates.extend(re.split(r"[;\n]+", str(site.get("aliases") or "")))
            for candidate in candidates:
                normalized = _normalized(candidate)
                if normalized and site not in exact[normalized]:
                    exact[normalized].append(site)
            number = _leading_number(site.get("address_line_1") or site.get("name") or "")
            if number and site not in numbers[number]:
                numbers[number].append(site)
        self.exact = exact
        self.numbers = numbers

    @staticmethod
    def _result(raw: str, site: dict | None, method: str, possible: list[dict] | None = None) -> dict:
        possible = possible or []
        return {
            "raw_name": raw,
            "name": site.get("name") if site else raw,
            "site_key": site.get("site_key") if site else "",
            "matched": bool(site),
            "method": method,
            "has_equals": "=" in raw,
            "possible_matches": sorted(
                {str(item.get("name") or "") for item in possible if item.get("name")},
                key=str.casefold,
            ),
        }

    def resolve(self, value: str) -> dict:
        raw = _clean(value)
        if not raw:
            return self._result(raw, None, "empty")
        candidates = _legacy_candidates(raw)

        exact_matches: dict[str, dict] = {}
        for candidate in candidates:
            for site in self.exact.get(_normalized(candidate), []):
                exact_matches[site["site_key"]] = site
        if len(exact_matches) == 1:
            return self._result(raw, next(iter(exact_matches.values())), "exact")
        if len(exact_matches) > 1:
            return self._result(raw, None, "ambiguous", list(exact_matches.values()))

        # Legacy labels frequently omit the street suffix.  A unique prefix
        # such as "1049 Woodland" may safely map to "1049 Woodland Ave".
        prefix_matches: dict[str, dict] = {}
        for candidate in candidates:
            normalized = _normalized(candidate)
            if not normalized:
                continue
            for site in self.sites:
                line = _normalized(site.get("address_line_1") or site.get("name") or "")
                if line == normalized or line.startswith(f"{normalized} "):
                    prefix_matches[site["site_key"]] = site
        if len(prefix_matches) == 1:
            return self._result(raw, next(iter(prefix_matches.values())), "address_prefix")
        if len(prefix_matches) > 1:
            return self._result(raw, None, "ambiguous", list(prefix_matches.values()))

        number_matches: dict[str, dict] = {}
        for candidate in candidates:
            number = _leading_number(candidate)
            matches = self.numbers.get(number, []) if number else []
            candidate_tokens = _street_tokens(candidate)
            if candidate_tokens:
                # A street number alone can safely use the unique-number
                # fallback. If the legacy value also names a street, require
                # a shared meaningful token so "2 Campo Bello" never becomes
                # "2 Lowery" merely because only Lowery is formalized so far.
                matches = [
                    site for site in matches
                    if candidate_tokens & _street_tokens(
                        site.get("address_line_1") or site.get("name") or ""
                    )
                ]
            if len(matches) == 1:
                number_matches[matches[0]["site_key"]] = matches[0]
            elif len(matches) > 1:
                for site in matches:
                    number_matches[site["site_key"]] = site
        if len(number_matches) == 1:
            return self._result(raw, next(iter(number_matches.values())), "street_number")
        if len(number_matches) > 1:
            return self._result(raw, None, "ambiguous", list(number_matches.values()))
        return self._result(raw, None, "unmatched")


def load_site_resolver(base, *, seed_if_empty: bool = False) -> SiteResolver:
    return SiteResolver(list_sites(base, seed_if_empty=seed_if_empty))


def site_selection_names(base, *, seed_if_empty: bool = False) -> tuple[list[str], list[str]]:
    """Return formal entry choices and canonical/fallback report choices."""
    sites = list_sites(base, seed_if_empty=seed_if_empty)
    formal = sorted(
        {site["name"] for site in sites if site["active"] and site["verified"]},
        key=str.casefold,
    )
    resolver = SiteResolver(sites)
    records = base.records(
        "Location Entries", field_names=("Location",), cache_seconds=300,
    )
    report_names = set(formal)
    for record in records:
        raw = text_value(field(record, "Location"))
        if raw:
            report_names.add(resolver.resolve(raw)["name"])
    return formal, sorted((name for name in report_names if name), key=str.casefold)


def historical_site_reviews(base, sites: list[dict] | None = None) -> list[dict]:
    """List historical labels that still need an address-book decision."""
    sites = sites if sites is not None else list_sites(base, seed_if_empty=True)
    resolver = SiteResolver(sites)
    stored = _lookup(sites)
    counts = Counter(
        text_value(field(record, "Location"))
        for record in base.records(
            "Location Entries", field_names=("Location",), cache_seconds=300,
        )
        if text_value(field(record, "Location"))
    )
    output = []
    for raw, occurrences in counts.items():
        resolution = resolver.resolve(raw)
        if resolution["matched"]:
            continue
        # Extracted draft records already appear in the regular Needs Review
        # table, so do not show a duplicate virtual row.
        if any(_normalized(candidate) in stored for candidate in _legacy_candidates(raw)):
            continue
        suggested = next(
            (candidate for candidate in _legacy_candidates(raw) if "=" not in candidate),
            re.sub(r"=+", " ", raw).strip(),
        )
        output.append({
            "raw_name": raw,
            "suggested_name": suggested,
            "first_number": _leading_number(suggested),
            "occurrences": occurrences,
            "has_equals": resolution["has_equals"],
            "reason": resolution["method"],
            "possible_matches": resolution["possible_matches"],
        })
    return sorted(output, key=lambda item: (-item["occurrences"], item["raw_name"].casefold()))


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
    normalized_values = {
        value for value in (
            _normalized(fields["Name"]),
            _normalized(fields["Full Address"]),
        ) if value
    }
    duplicate = next(
        (
            site for site in sites
            if site["site_key"] != key
            and normalized_values & {
                _normalized(site["name"]),
                _normalized(site["full_address"]),
            }
        ),
        None,
    )
    if duplicate:
        historical_source = _clean(body.get("source")).casefold() in {
            "historical review", "work-entry extraction",
        }
        if historical_source:
            old_name = existing.get(supplied_key, {}).get("name", "")
            alias_values = [
                *re.split(r"[;\n]+", duplicate.get("aliases") or ""),
                *re.split(r"[;\n]+", str(body.get("aliases") or "")),
                old_name,
            ]
            merged = {
                **duplicate,
                "aliases": "; ".join(dict.fromkeys(
                    _clean(value, 240) for value in alias_values
                    if _clean(value, 240)
                    and _normalized(value) != _normalized(duplicate["name"])
                )),
                "source": duplicate.get("source") or "address library",
            }
            merged_fields = _site_fields(
                merged, duplicate["site_key"], source=merged["source"],
            )
            base.set_by_key(TABLE, KEY_FIELD, duplicate["site_key"], merged_fields)
            return site_profile({"fields": merged_fields})
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
    resolver = SiteResolver(sites)
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
        if resolver.resolve(location)["matched"]:
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
            base = DataStore()
            sites = list_sites(base, seed_if_empty=True)
            historical_reviews = historical_site_reviews(base, sites)
            resolver = SiteResolver(sites)
            visible_sites = []
            covered_history_records = 0
            for site in sites:
                resolution = resolver.resolve(site["name"])
                covered = (
                    site["source"] == "work-entry extraction"
                    and not site["verified"]
                    and resolution["matched"]
                    and resolution["site_key"] != site["site_key"]
                )
                if covered:
                    covered_history_records += 1
                else:
                    visible_sites.append(site)
            json_response(self, {
                "sites": visible_sites,
                "historical_reviews": historical_reviews,
                "covered_history_records": covered_history_records,
                "totals": {
                    "sites": len(visible_sites),
                    "active": sum(site["active"] for site in visible_sites),
                    "archived": sum(not site["active"] for site in visible_sites),
                    "verified": sum(site["verified"] for site in visible_sites),
                    "needs_review": sum(not site["verified"] for site in visible_sites) + len(historical_reviews),
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
