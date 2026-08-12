from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import math
import os
import re
from zoneinfo import ZoneInfo

from api._lark import LarkAPIError
from api._lark_base import LarkBase, text_value
from api._lark_sheet import (
    WORKBOOK_SETTING,
    configured_workbook,
    worker_profiles,
)
from api._postgres_base import KEY_FIELDS, PostgresBase, lark_mirror_enabled
from api._work_log import WORK_LOG_TABLE, work_log_row
from api.lark.setup import CHECKBOX, DATE, NUMBER, SCHEMA, TEXT


WORK_RECORD_TABLES = {"Work Days", "Location Entries"}
_LOCATION_DAY_KEY = re.compile(r"^(.*\|\d{4}-\d{2}-\d{2})(?:\|.*)?$")


def _number_field(value, table_name: str, field_name: str):
    """Convert numeric mirror fields before sending them to Lark Base.

    PostgreSQL imports and browser edits can leave a numeric value as a
    string. Lark's Base API reports the unhelpful ``NumberFieldConvFail`` for
    those values, so validate it here and identify the actual field.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise LarkAPIError(
            f"{table_name}.{field_name} must be a number, got boolean.",
            status=422,
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise LarkAPIError(
            f"{table_name}.{field_name} must be a number, got {value!r}.",
            status=422,
        ) from error
    if not math.isfinite(number):
        raise LarkAPIError(
            f"{table_name}.{field_name} must be finite, got {value!r}.",
            status=422,
        )
    return int(number) if number.is_integer() else number


def _checkbox_field(value, table_name: str, field_name: str):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"true", "yes", "y", "1", "on"}:
        return True
    if normalized in {"false", "no", "n", "0", "off"}:
        return False
    raise LarkAPIError(
        f"{table_name}.{field_name} must be a checkbox value, got {value!r}.",
        status=422,
    )


def _datetime_field(value, table_name: str, field_name: str):
    """Convert PostgreSQL dates/ISO timestamps to Lark millisecond timestamps."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise LarkAPIError(
            f"{table_name}.{field_name} must be a date/time, got boolean.",
            status=422,
        )

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if not math.isfinite(timestamp):
            raise LarkAPIError(
                f"{table_name}.{field_name} must be a finite timestamp.",
                status=422,
            )
        # Accept both seconds and milliseconds from historical imports.
        if abs(timestamp) < 100_000_000_000:
            timestamp *= 1000
        return int(round(timestamp))

    raw = str(value).strip()
    try:
        numeric = float(raw)
    except ValueError:
        numeric = None
    if numeric is not None:
        return _datetime_field(numeric, table_name, field_name)

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(raw[:10])
        except ValueError as error:
            raise LarkAPIError(
                f"{table_name}.{field_name} must be an ISO date/time, got {value!r}.",
                status=422,
            ) from error
        parsed = datetime.combine(parsed_date, datetime.min.time())

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=ZoneInfo(
                os.environ.get("APP_TIME_ZONE", "America/Los_Angeles")
            )
        )
    return int(round(parsed.timestamp() * 1000))


def normalize_mirror_fields(table_name: str, fields: dict) -> dict:
    """Normalize fields whose Lark types are stricter than PostgreSQL JSON."""
    normalized = dict(fields or {})
    field_types = dict(SCHEMA.get(table_name, ()))
    for field_name, field_type in field_types.items():
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        if field_type == NUMBER:
            normalized[field_name] = _number_field(
                value, table_name, field_name
            )
        elif field_type == CHECKBOX:
            normalized[field_name] = _checkbox_field(
                value, table_name, field_name
            )
        elif field_type == DATE:
            normalized[field_name] = _datetime_field(
                value, table_name, field_name
            )
        elif field_type == TEXT and value is not None:
            normalized[field_name] = text_value(value)
    return normalized


def latest_events(events: list[dict]) -> dict[tuple[str, str], dict]:
    """Collapse repeated changes so Lark receives only the latest desired state."""
    latest: dict[tuple[str, str], dict] = {}
    for event in events:
        latest[(event["table_name"], event["key_value"])] = event
    return latest


def work_day_key(event: dict) -> str:
    if event["table_name"] == "Work Days":
        return str(event.get("key_value") or "")
    fields = event.get("fields") or {}
    day_key = str(fields.get("Work Day Key") or "").strip()
    if day_key:
        return day_key
    match = _LOCATION_DAY_KEY.match(str(event.get("key_value") or ""))
    return match.group(1) if match else ""


def _sync_direct_table(
    database: PostgresBase,
    mirror: LarkBase,
    table_name: str,
    desired: dict[tuple[str, str], dict],
) -> None:
    if table_name not in KEY_FIELDS:
        raise LarkAPIError(f"Unsupported mirror table {table_name!r}.")
    table_desired = [
        {
            **event,
            "fields": normalize_mirror_fields(table_name, event.get("fields") or {}),
        }
        for (event_table, _), event in desired.items()
        if event_table == table_name
    ]
    mappings = database.mirror_record_ids(
        table_name,
        [event["key_value"] for event in table_desired],
    )
    delete_ids = [
        mappings[event["key_value"]]
        for event in table_desired
        if event["operation"] == "delete" and event["key_value"] in mappings
    ]
    delete_keys = [
        event["key_value"]
        for event in table_desired
        if event["operation"] == "delete"
    ]
    mapped_upserts = [
        {
            "record_id": mappings[event["key_value"]],
            "fields": event["fields"],
        }
        for event in table_desired
        if event["operation"] == "upsert" and event["key_value"] in mappings
    ]
    creates = [
        event
        for event in table_desired
        if event["operation"] == "upsert" and event["key_value"] not in mappings
    ]
    if delete_ids:
        mirror.delete_record_ids(table_name, delete_ids)
        database.delete_mirror_keys(table_name, delete_keys)
    if mapped_upserts:
        mirror.batch_update_record_ids(table_name, mapped_upserts)
    if creates:
        created_ids = mirror.batch_create_records(
            table_name,
            [event["fields"] for event in creates],
        )
        database.set_mirror_record_ids(
            table_name,
            {
                event["key_value"]: record_id
                for event, record_id in zip(creates, created_ids)
            },
        )


def _sync_work_log(
    database: PostgresBase,
    mirror: LarkBase,
    events: list[dict],
) -> None:
    day_keys = list(dict.fromkeys(filter(None, (work_day_key(event) for event in events))))
    if not day_keys:
        raise LarkAPIError("A work-record sync event is missing its worker/day key.")

    day_rows, location_rows = database.work_log_records(day_keys)
    days_by_key = {
        str(day.get("Work Day Key") or ""): day
        for day in day_rows
        if day.get("Work Day Key")
    }
    locations_by_day: dict[str, list[dict]] = defaultdict(list)
    for location in location_rows:
        day_key = str(location.get("Work Day Key") or "")
        if day_key:
            locations_by_day[day_key].append(location)

    mappings = database.mirror_record_ids(WORK_LOG_TABLE, day_keys)
    missing_day_keys = [key for key in day_keys if key not in days_by_key]
    delete_ids = [mappings[key] for key in missing_day_keys if key in mappings]
    if delete_ids:
        mirror.delete_record_ids(WORK_LOG_TABLE, delete_ids)
        database.delete_mirror_keys(WORK_LOG_TABLE, missing_day_keys)

    desired_rows = {
        key: normalize_mirror_fields(
            WORK_LOG_TABLE,
            work_log_row(day, locations_by_day.get(key, [])),
        )
        for key, day in days_by_key.items()
    }
    updates = [
        {"record_id": mappings[key], "fields": fields}
        for key, fields in desired_rows.items()
        if key in mappings
    ]
    creates = [
        (key, fields)
        for key, fields in desired_rows.items()
        if key not in mappings
    ]
    if updates:
        mirror.batch_update_record_ids(WORK_LOG_TABLE, updates)
    if creates:
        created_ids = mirror.batch_create_records(
            WORK_LOG_TABLE,
            [fields for _, fields in creates],
        )
        database.set_mirror_record_ids(
            WORK_LOG_TABLE,
            {
                key: record_id
                for (key, _), record_id in zip(creates, created_ids)
            },
        )

    configured = configured_workbook(database)
    if configured:
        workbook, config = configured
        workers = worker_profiles(database.records("Workers", cache_seconds=0))
        result = workbook.sync_work_rows(
            workers,
            list(desired_rows.values()),
            missing_day_keys,
            config,
        )
        config["worker_rows"] = result["worker_rows"]
        database.set_setting(WORKBOOK_SETTING, config)


def synchronize_lark(limit: int = 200) -> dict:
    database = PostgresBase()
    if not lark_mirror_enabled():
        return {
            "enabled": False,
            "processed": 0,
            "message": "Lark mirroring is disabled.",
        }

    events = database.claim_sync_events(limit)
    if not events:
        return {**database.sync_status(), "processed": 0}

    desired = latest_events(events)
    events_by_table: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        events_by_table[event["table_name"]].append(event)

    mirror = LarkBase()
    processed = 0
    failed_tables: list[str] = []
    work_events = [
        event for event in events if event["table_name"] in WORK_RECORD_TABLES
    ]
    if work_events:
        event_ids = [event["id"] for event in work_events]
        try:
            _sync_work_log(database, mirror, work_events)
            database.complete_sync_events(event_ids)
            processed += len(event_ids)
        except Exception as error:
            failed_tables.append(WORK_LOG_TABLE)
            database.fail_sync_events(
                event_ids,
                f"{type(error).__name__}: {error}",
            )

    for table_name, table_events in events_by_table.items():
        if table_name in WORK_RECORD_TABLES:
            continue
        event_ids = [event["id"] for event in table_events]
        try:
            _sync_direct_table(
                database,
                mirror,
                table_name,
                desired,
            )
            if table_name == "Workers":
                configured = configured_workbook(database)
                if configured:
                    workbook, config = configured
                    workers = worker_profiles(
                        database.records("Workers", cache_seconds=0)
                    )
                    result = workbook.sync_workers(workers, config)
                    config["worker_rows"] = result["worker_rows"]
                    database.set_setting(WORKBOOK_SETTING, config)
            database.complete_sync_events(event_ids)
            processed += len(event_ids)
        except Exception as error:
            failed_tables.append(table_name)
            database.fail_sync_events(
                event_ids,
                f"{type(error).__name__}: {error}",
            )

    status = database.sync_status()
    return {
        **status,
        "processed": processed,
        "failed_tables": failed_tables,
    }
