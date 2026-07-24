from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any

from api._lark import LarkAPIError
from api._lark_base import REQUIRED_TABLES, date_value, field, text_value


KEY_FIELDS = {
    "Workers": "Worker Key",
    "Work Days": "Work Day Key",
    "Location Entries": "Location Entry Key",
    "Cost Centers": "Cost Center ID",
    "Payroll Checks": "Payroll Check Key",
    "Audit Log": "Audit Key",
}

_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[float, list[dict]]] = {}


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
                    cursor.executemany(
                        """
                        INSERT INTO workforce_tables (table_name)
                        VALUES (%s)
                        ON CONFLICT (table_name) DO NOTHING
                        """,
                        [(name,) for name in sorted(REQUIRED_TABLES)],
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
                        DELETE FROM workforce_records
                        WHERE table_name = %s AND record_id = ANY(%s)
                        """,
                        (table_name, record_ids),
                    )
                    deleted = cursor.rowcount
        except LarkAPIError:
            raise
        except Exception as error:
            raise LarkAPIError(
                f"PostgreSQL delete failed: {type(error).__name__}.",
                status=503,
            ) from error
        self.invalidate_records(table_name)
        return int(deleted)
