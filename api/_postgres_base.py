from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any

from api._lark import LarkAPIError
from api._lark_base import REQUIRED_TABLES, date_value, field, text_value
from api._work_log import WORK_LOG_TABLE


KEY_FIELDS = {
    "Workers": "Worker Key",
    "Work Days": "Work Day Key",
    "Location Entries": "Location Entry Key",
    "Cost Centers": "Cost Center ID",
    "Payroll Checks": "Payroll Check Key",
    "Audit Log": "Audit Key",
}

_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[float, list[dict]]] = {}


def lark_mirror_enabled() -> bool:
    return (
        os.environ.get("DATA_BACKEND", "lark").strip().casefold() == "postgres"
        and os.environ.get("LARK_MIRROR_ENABLED", "").strip().casefold()
        in {"1", "true", "yes", "on"}
    )


def _driver():
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as error:
        raise LarkAPIError(
            "PostgreSQL support is not installed. Deploy with requirements.txt.",
            status=503,
        ) from error
    return psycopg, Jsonb


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise LarkAPIError("DATABASE_URL is not configured.", status=503)
    return value


def _connection():
    psycopg, _ = _driver()
    try:
        return psycopg.connect(_database_url(), connect_timeout=10)
    except Exception as error:
        raise LarkAPIError(
            f"PostgreSQL is unavailable: {type(error).__name__}.",
            status=503,
        ) from error


def _decode_fields(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _quoted_value(raw: str) -> str:
    return raw.replace(r"\"", '"').replace(r"\\", "\\")


def _matches_filter(record: dict, formula: str) -> bool:
    if not formula:
        return True
    fields = record.get("fields") or {}
    for name, operator, raw in re.findall(
        r'CurrentValue\.\[([^\]]+)\]\s*(>=|<=)\s*TODATE\("((?:\\.|[^"])*)"\)',
        formula,
    ):
        current = date_value(fields.get(name))
        expected = _quoted_value(raw)
        if not current or (operator == ">=" and current < expected) or (
            operator == "<=" and current > expected
        ):
            return False
    for name, raw in re.findall(
        r'CurrentValue\.\[([^\]]+)\]\s*=\s*TODATE\("((?:\\.|[^"])*)"\)',
        formula,
    ):
        if date_value(fields.get(name)) != _quoted_value(raw):
            return False
    for name, raw in re.findall(
        r'CurrentValue\.\[([^\]]+)\]\s*=\s*"((?:\\.|[^"])*)"',
        formula,
    ):
        if text_value(fields.get(name)) != _quoted_value(raw):
            return False
    return True


class PostgresBase:
    """Record-compatible PostgreSQL adapter used by existing report handlers."""

    def table_ids(self) -> dict[str, str]:
        return {name: name for name in REQUIRED_TABLES}

    def ensure_schema(self) -> None:
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS workforce_tables (
                            table_name TEXT PRIMARY KEY,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS workforce_records (
                            table_name TEXT NOT NULL
                                REFERENCES workforce_tables(table_name)
                                ON DELETE CASCADE,
                            record_id TEXT NOT NULL,
                            key_field TEXT NOT NULL,
                            key_value TEXT NOT NULL,
                            fields JSONB NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            PRIMARY KEY (table_name, record_id),
                            UNIQUE (table_name, key_value)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS workforce_records_table_updated
                        ON workforce_records (table_name, updated_at DESC)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS workforce_records_work_day_key
                        ON workforce_records (
                            table_name,
                            ((fields ->> 'Work Day Key'))
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS workforce_sync_outbox (
                            id BIGSERIAL PRIMARY KEY,
                            table_name TEXT NOT NULL
                                REFERENCES workforce_tables(table_name)
                                ON DELETE CASCADE,
                            key_field TEXT NOT NULL,
                            key_value TEXT NOT NULL,
                            operation TEXT NOT NULL
                                CHECK (operation IN ('upsert', 'delete')),
                            fields JSONB,
                            status TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'processing', 'synced')),
                            attempts INTEGER NOT NULL DEFAULT 0,
                            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            locked_until TIMESTAMPTZ,
                            last_error TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            synced_at TIMESTAMPTZ
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS workforce_sync_outbox_pending
                        ON workforce_sync_outbox (status, available_at, id)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS workforce_lark_mirror_keys (
                            table_name TEXT NOT NULL
                                REFERENCES workforce_tables(table_name)
                                ON DELETE CASCADE,
                            key_value TEXT NOT NULL,
                            lark_record_id TEXT NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            PRIMARY KEY (table_name, key_value),
                            UNIQUE (table_name, lark_record_id)
                        )
                        """
                    )
                    cursor.executemany(
                        """
                        INSERT INTO workforce_tables (table_name)
                        VALUES (%s)
                        ON CONFLICT (table_name) DO NOTHING
                        """,
                        [
                            (name,)
                            for name in sorted(REQUIRED_TABLES | {WORK_LOG_TABLE})
                        ],
                    )
                    cursor.execute(
                        """
                        INSERT INTO workforce_lark_mirror_keys
                            (table_name, key_value, lark_record_id)
                        SELECT table_name, key_value, record_id
                        FROM workforce_records
                        WHERE record_id LIKE 'rec%'
                        ON CONFLICT (table_name, key_value) DO NOTHING
                        """
                    )
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"Could not initialize PostgreSQL: {type(error).__name__}.",
                status=503,
            ) from error

    def missing_tables(self) -> list[str]:
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT table_name FROM workforce_tables")
                    present = {str(row[0]) for row in cursor.fetchall()}
            return sorted(REQUIRED_TABLES - present)
        except LarkAPIError:
            raise
        except Exception as error:
            # Undefined-table errors are expected before the one-time setup.
            raise LarkAPIError(
                "PostgreSQL schema is not initialized. Run database setup first.",
                status=503,
            ) from error

    def records(
        self,
        table_name: str,
        *,
        filter_formula: str = "",
        field_names: tuple[str, ...] = (),
        cache_seconds: int = 45,
    ) -> list[dict]:
        cache_key = (table_name, filter_formula, field_names)
        cached = _CACHE.get(cache_key)
        if cache_seconds and cached and time.monotonic() < cached[0]:
            return list(cached[1])
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT record_id, fields
                        FROM workforce_records
                        WHERE table_name = %s
                        """,
                        (table_name,),
                    )
                    output = [
                        {"record_id": str(record_id), "fields": _decode_fields(fields)}
                        for record_id, fields in cursor.fetchall()
                    ]
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"PostgreSQL read failed: {type(error).__name__}.",
                status=503,
            ) from error
        output = [record for record in output if _matches_filter(record, filter_formula)]
        if field_names:
            output = [
                {
                    "record_id": record["record_id"],
                    "fields": {
                        name: record["fields"].get(name)
                        for name in field_names
                        if name in record["fields"]
                    },
                }
                for record in output
            ]
        if cache_seconds:
            _CACHE[cache_key] = (time.monotonic() + cache_seconds, list(output))
        return output

    def invalidate_records(self, table_name: str) -> None:
        for key in list(_CACHE):
            if key[0] == table_name:
                _CACHE.pop(key, None)

    @staticmethod
    def _enqueue_upserts(cursor, table_name: str, key_field: str, rows: list[dict]) -> None:
        if not lark_mirror_enabled() or not rows:
            return
        _, Jsonb = _driver()
        cursor.executemany(
            """
            INSERT INTO workforce_sync_outbox
                (table_name, key_field, key_value, operation, fields)
            VALUES (%s, %s, %s, 'upsert', %s)
            """,
            [
                (
                    table_name,
                    key_field,
                    text_value(row.get(key_field)),
                    Jsonb(row),
                )
                for row in rows
            ],
        )

    @staticmethod
    def _enqueue_deletes(
        cursor,
        table_name: str,
        rows: list[tuple[str, str, dict]],
    ) -> None:
        if not lark_mirror_enabled() or not rows:
            return
        _, Jsonb = _driver()
        cursor.executemany(
            """
            INSERT INTO workforce_sync_outbox
                (table_name, key_field, key_value, operation, fields)
            VALUES (%s, %s, %s, 'delete', %s)
            """,
            [
                (table_name, key_field, key_value, Jsonb(fields))
                for key_field, key_value, fields in rows
            ],
        )

    def import_records(self, table_name: str, records: list[dict]) -> int:
        key_field = KEY_FIELDS[table_name]
        _, Jsonb = _driver()
        rows = []
        for record in records:
            fields = record.get("fields") or {}
            key = text_value(fields.get(key_field))
            if not key:
                continue
            rows.append(
                (
                    table_name,
                    str(record.get("record_id") or uuid.uuid4()),
                    key_field,
                    key,
                    Jsonb(fields),
                )
            )
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO workforce_records
                            (table_name, record_id, key_field, key_value, fields)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (table_name, key_value) DO UPDATE SET
                            key_field = EXCLUDED.key_field,
                            fields = EXCLUDED.fields,
                            updated_at = NOW()
                        """,
                        rows,
                    )
                    cursor.executemany(
                        """
                        INSERT INTO workforce_lark_mirror_keys
                            (table_name, key_value, lark_record_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (table_name, key_value) DO UPDATE SET
                            lark_record_id = EXCLUDED.lark_record_id,
                            updated_at = NOW()
                        """,
                        [
                            (
                                table_name,
                                text_value((record.get("fields") or {}).get(key_field)),
                                str(record.get("record_id") or ""),
                            )
                            for record in records
                            if text_value((record.get("fields") or {}).get(key_field))
                            and str(record.get("record_id") or "")
                        ],
                    )
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"PostgreSQL import failed: {type(error).__name__}.",
                status=503,
            ) from error
        self.invalidate_records(table_name)
        return len(rows)

    def batch_set_by_key(
        self,
        table_name: str,
        key_field: str,
        rows: list[dict],
        *,
        existing_records: list[dict] | None = None,
    ) -> dict:
        existing_records = (
            existing_records if existing_records is not None else self.records(table_name)
        )
        existing = {
            text_value(field(record, key_field)): record
            for record in existing_records
            if text_value(field(record, key_field))
        }
        supplied: set[str] = set()
        creates = 0
        updates = 0
        payload = []
        _, Jsonb = _driver()
        for row in rows:
            key = text_value(row.get(key_field))
            if not key or key in supplied:
                raise LarkAPIError(
                    f"Invalid or duplicate {table_name} key {key!r}.",
                    status=400,
                )
            supplied.add(key)
            match = existing.get(key)
            creates += int(match is None)
            updates += int(match is not None)
            payload.append(
                (
                    table_name,
                    str((match or {}).get("record_id") or uuid.uuid4()),
                    key_field,
                    key,
                    Jsonb(row),
                )
            )
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO workforce_records
                            (table_name, record_id, key_field, key_value, fields)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (table_name, key_value) DO UPDATE SET
                            key_field = EXCLUDED.key_field,
                            fields = EXCLUDED.fields,
                            updated_at = NOW()
                        """,
                        payload,
                    )
                    self._enqueue_upserts(cursor, table_name, key_field, rows)
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"PostgreSQL write failed: {type(error).__name__}.",
                status=503,
            ) from error
        self.invalidate_records(table_name)
        return {"created": creates, "updated": updates}

    def set_by_key(
        self, table_name: str, key_field: str, key: str, fields: dict
    ) -> dict:
        existing = {
            text_value(field(record, key_field)): record
            for record in self.records(table_name)
        }
        match = existing.get(key)
        result = self.batch_set_by_key(
            table_name, key_field, [fields], existing_records=list(existing.values()),
        )
        saved = next(
            (
                record for record in self.records(table_name, cache_seconds=0)
                if text_value(field(record, key_field)) == key
            ),
            {},
        )
        return {
            "created": bool(result["created"]),
            "record_id": saved.get("record_id", (match or {}).get("record_id", "")),
        }

    def delete_record_ids(self, table_name: str, record_ids: list[str]) -> int:
        record_ids = [value for value in dict.fromkeys(record_ids) if value]
        if not record_ids:
            return 0
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT key_field, key_value, fields
                        FROM workforce_records
                        WHERE table_name = %s AND record_id = ANY(%s)
                        """,
                        (table_name, record_ids),
                    )
                    deleted_keys = [
                        (str(key_field), str(key_value), _decode_fields(fields))
                        for key_field, key_value, fields in cursor.fetchall()
                    ]
                    cursor.execute(
                        """
                        DELETE FROM workforce_records
                        WHERE table_name = %s AND record_id = ANY(%s)
                        """,
                        (table_name, record_ids),
                    )
                    deleted = cursor.rowcount
                    self._enqueue_deletes(cursor, table_name, deleted_keys)
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"PostgreSQL delete failed: {type(error).__name__}.",
                status=503,
            ) from error
        self.invalidate_records(table_name)
        return int(deleted)

    def enqueue_sync_snapshot(self) -> int:
        """Queue the current PostgreSQL state for a one-time Lark reconciliation."""
        if not lark_mirror_enabled():
            raise LarkAPIError("Lark mirroring is not enabled.", status=409)
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workforce_sync_outbox
                            (table_name, key_field, key_value, operation, fields)
                        SELECT table_name, key_field, key_value, 'upsert', fields
                        FROM workforce_records
                        """
                    )
                    queued = cursor.rowcount
            return int(queued)
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"Could not queue the Lark snapshot: {type(error).__name__}.",
                status=503,
            ) from error

    def enqueue_work_log_snapshot(self) -> int:
        """Queue one projection event for every current worker/day record."""
        if not lark_mirror_enabled():
            raise LarkAPIError("Lark mirroring is not enabled.", status=409)
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO workforce_sync_outbox
                            (table_name, key_field, key_value, operation, fields)
                        SELECT table_name, key_field, key_value, 'upsert', fields
                        FROM workforce_records
                        WHERE table_name = 'Work Days'
                        """
                    )
                    queued = cursor.rowcount
            return int(queued)
        except Exception as error:
            raise LarkAPIError(
                f"Could not queue the Work Log snapshot: {type(error).__name__}.",
                status=503,
            ) from error

    def work_log_records(self, day_keys: list[str]) -> tuple[list[dict], list[dict]]:
        day_keys = [value for value in dict.fromkeys(day_keys) if value]
        if not day_keys:
            return [], []
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT fields
                        FROM workforce_records
                        WHERE table_name = 'Work Days'
                          AND key_value = ANY(%s)
                        """,
                        (day_keys,),
                    )
                    days = [_decode_fields(row[0]) for row in cursor.fetchall()]
                    cursor.execute(
                        """
                        SELECT fields
                        FROM workforce_records
                        WHERE table_name = 'Location Entries'
                          AND (fields ->> 'Work Day Key') = ANY(%s)
                        ORDER BY
                            COALESCE((fields ->> 'Display Order')::numeric, 0),
                            key_value
                        """,
                        (day_keys,),
                    )
                    locations = [_decode_fields(row[0]) for row in cursor.fetchall()]
            return days, locations
        except Exception as error:
            raise LarkAPIError(
                f"Could not build Work Log records: {type(error).__name__}.",
                status=503,
            ) from error

    def mirror_record_ids(self, table_name: str, key_values: list[str]) -> dict[str, str]:
        key_values = [value for value in dict.fromkeys(key_values) if value]
        if not key_values:
            return {}
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT key_value, lark_record_id
                        FROM workforce_lark_mirror_keys
                        WHERE table_name = %s AND key_value = ANY(%s)
                        """,
                        (table_name, key_values),
                    )
                    return {
                        str(key_value): str(record_id)
                        for key_value, record_id in cursor.fetchall()
                    }
        except Exception as error:
            raise LarkAPIError(
                f"Could not read Lark record mappings: {type(error).__name__}.",
                status=503,
            ) from error

    def set_mirror_record_ids(self, table_name: str, mappings: dict[str, str]) -> None:
        mappings = {
            str(key): str(record_id)
            for key, record_id in mappings.items()
            if key and record_id
        }
        if not mappings:
            return
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO workforce_lark_mirror_keys
                            (table_name, key_value, lark_record_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (table_name, key_value) DO UPDATE SET
                            lark_record_id = EXCLUDED.lark_record_id,
                            updated_at = NOW()
                        """,
                        [
                            (table_name, key, record_id)
                            for key, record_id in mappings.items()
                        ],
                    )
        except Exception as error:
            raise LarkAPIError(
                f"Could not save Lark record mappings: {type(error).__name__}.",
                status=503,
            ) from error

    def delete_mirror_keys(self, table_name: str, key_values: list[str]) -> None:
        key_values = [value for value in dict.fromkeys(key_values) if value]
        if not key_values:
            return
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM workforce_lark_mirror_keys
                        WHERE table_name = %s AND key_value = ANY(%s)
                        """,
                        (table_name, key_values),
                    )
        except Exception as error:
            raise LarkAPIError(
                f"Could not delete Lark record mappings: {type(error).__name__}.",
                status=503,
            ) from error

    def claim_sync_events(self, limit: int = 200) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workforce_sync_outbox
                        SET status = 'pending', locked_until = NULL
                        WHERE status = 'processing' AND locked_until < NOW()
                        """
                    )
                    cursor.execute(
                        """
                        SELECT id, table_name, key_field, key_value, operation, fields
                        FROM workforce_sync_outbox
                        WHERE status = 'pending' AND available_at <= NOW()
                        ORDER BY id
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                        """,
                        (limit,),
                    )
                    rows = cursor.fetchall()
                    ids = [int(row[0]) for row in rows]
                    if ids:
                        cursor.execute(
                            """
                            UPDATE workforce_sync_outbox
                            SET status = 'processing',
                                attempts = attempts + 1,
                                locked_until = NOW() + INTERVAL '5 minutes'
                            WHERE id = ANY(%s)
                            """,
                            (ids,),
                        )
            return [
                {
                    "id": int(row[0]),
                    "table_name": str(row[1]),
                    "key_field": str(row[2]),
                    "key_value": str(row[3]),
                    "operation": str(row[4]),
                    "fields": _decode_fields(row[5]),
                }
                for row in rows
            ]
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"Could not read the Lark sync queue: {type(error).__name__}.",
                status=503,
            ) from error

    def complete_sync_events(self, event_ids: list[int]) -> None:
        if not event_ids:
            return
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workforce_sync_outbox
                        SET status = 'synced',
                            synced_at = NOW(),
                            locked_until = NULL,
                            last_error = NULL
                        WHERE id = ANY(%s)
                        """,
                        (event_ids,),
                    )
                    cursor.execute(
                        """
                        DELETE FROM workforce_sync_outbox
                        WHERE status = 'synced'
                          AND synced_at < NOW() - INTERVAL '7 days'
                        """
                    )
        except Exception as error:
            raise LarkAPIError(
                f"Could not complete the Lark sync queue: {type(error).__name__}.",
                status=503,
            ) from error

    def fail_sync_events(self, event_ids: list[int], error: str) -> None:
        if not event_ids:
            return
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workforce_sync_outbox
                        SET status = 'pending',
                            available_at = NOW() + INTERVAL '30 seconds',
                            locked_until = NULL,
                            last_error = %s
                        WHERE id = ANY(%s)
                        """,
                        (error[:500], event_ids),
                    )
        except Exception as queue_error:
            raise LarkAPIError(
                f"Could not retry the Lark sync queue: {type(queue_error).__name__}.",
                status=503,
            ) from queue_error

    def sync_status(self) -> dict:
        try:
            with _connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (
                                WHERE status IN ('pending', 'processing')
                            ) AS pending,
                            COUNT(*) FILTER (
                                WHERE status = 'pending' AND last_error IS NOT NULL
                            ) AS retrying,
                            COUNT(*) FILTER (
                                WHERE status = 'synced'
                                  AND synced_at >= NOW() - INTERVAL '24 hours'
                            ) AS synced_last_24h,
                            MAX(synced_at) AS last_synced_at
                        FROM workforce_sync_outbox
                        """
                    )
                    pending, retrying, recent, last_synced = cursor.fetchone()
            return {
                "enabled": lark_mirror_enabled(),
                "pending": int(pending or 0),
                "retrying": int(retrying or 0),
                "synced_last_24h": int(recent or 0),
                "last_synced_at": last_synced.isoformat() if last_synced else "",
            }
        except Exception as error:
            raise LarkAPIError(
                f"Could not inspect the Lark sync queue: {type(error).__name__}.",
                status=503,
            ) from error
