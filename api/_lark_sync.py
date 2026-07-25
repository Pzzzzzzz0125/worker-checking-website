from __future__ import annotations

from collections import defaultdict

from api._lark import LarkAPIError
from api._lark_base import LarkBase
from api._postgres_base import KEY_FIELDS, PostgresBase, lark_mirror_enabled


def latest_events(events: list[dict]) -> dict[tuple[str, str], dict]:
    """Collapse repeated changes so Lark receives only the latest desired state."""
    latest: dict[tuple[str, str], dict] = {}
    for event in events:
        latest[(event["table_name"], event["key_value"])] = event
    return latest


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
    for table_name, table_events in events_by_table.items():
        event_ids = [event["id"] for event in table_events]
        try:
            if table_name not in KEY_FIELDS:
                raise LarkAPIError(f"Unsupported mirror table {table_name!r}.")
            key_field = KEY_FIELDS[table_name]
            table_desired = [
                event
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
                if event["operation"] == "delete"
                and event["key_value"] in mappings
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
                if event["operation"] == "upsert"
                and event["key_value"] in mappings
            ]
            creates = [
                event
                for event in table_desired
                if event["operation"] == "upsert"
                and event["key_value"] not in mappings
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
