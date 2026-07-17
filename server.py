#!/usr/bin/env python3
"""Local worker-hours web app.

Run with:
    python3 server.py
Then open http://localhost:8000
"""

from __future__ import annotations

import io
import json
import calendar
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import traceback
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from worklog_parser import (
    format_work_cell,
    normalize_name,
    normalize_space,
    parse_work_cell,
)
from xlsx_workbook import (
    read_cost_centers,
    read_workbook,
    read_worker_information,
    update_workbook,
)


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
UPLOADS = DATA / "imports"
DB_PATH = DATA / "worklog.sqlite3"
DEFAULT_PORT = 8000


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS workers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    workbook_name TEXT NOT NULL,
    name_occurrence INTEGER NOT NULL DEFAULT 1,
    area TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS worker_aliases (
    alias TEXT PRIMARY KEY,
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS worker_compensation (
    worker_id INTEGER PRIMARY KEY REFERENCES workers(id) ON DELETE CASCADE,
    daily_rate REAL,
    pay_schedule TEXT NOT NULL DEFAULT '',
    payment_method TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cost_centers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS work_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    work_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('worked', 'off', 'unknown')),
    total_hours REAL,
    extra_pay REAL NOT NULL DEFAULT 0,
    start_time TEXT NOT NULL DEFAULT '',
    end_time TEXT NOT NULL DEFAULT '',
    work_kind TEXT NOT NULL DEFAULT 'None',
    cost_center_id TEXT NOT NULL DEFAULT '',
    cost_center_name TEXT NOT NULL DEFAULT '',
    original_text TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'app',
    confidence TEXT NOT NULL DEFAULT 'high',
    warning TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(worker_id, work_date)
);
CREATE TABLE IF NOT EXISTS work_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_day_id INTEGER NOT NULL REFERENCES work_days(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    hours REAL
);
CREATE TABLE IF NOT EXISTS work_day_cost_centers (
    work_day_id INTEGER NOT NULL REFERENCES work_days(id) ON DELETE CASCADE,
    cost_center_id TEXT NOT NULL,
    cost_center_name TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(work_day_id, cost_center_id)
);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    workbook_year INTEGER NOT NULL,
    status TEXT NOT NULL,
    added_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS import_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
    worker_name TEXT NOT NULL,
    worker_occurrence INTEGER NOT NULL DEFAULT 1,
    work_date TEXT NOT NULL,
    current_json TEXT,
    proposed_json TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id INTEGER,
    work_date TEXT,
    action TEXT NOT NULL,
    old_json TEXT,
    new_json TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payroll_checks (
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    period_start TEXT NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT,
    PRIMARY KEY(worker_id, period_start)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_days_date ON work_days(work_date);
CREATE INDEX IF NOT EXISTS idx_work_days_worker ON work_days(worker_id);
"""


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def setting(connection: sqlite3.Connection, key: str, value: str | None = None) -> str | None:
    if value is not None:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        return value
    row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def init_database() -> None:
    DATA.mkdir(exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    with connect() as connection:
        connection.executescript(SCHEMA)
        migrate_database(connection)
        has_data = connection.execute("SELECT 1 FROM workers LIMIT 1").fetchone()
        if not has_data:
            workbooks = sorted(
                path for path in ROOT.glob("*.xlsx")
                if "worker" in path.name.casefold()
            )
            if workbooks:
                inferred = re.search(r"\b(20\d{2})\b", workbooks[0].name)
                year = int(inferred.group(1)) if inferred else date.today().year
                import_baseline(connection, workbooks[0], year)
        template = setting(connection, "template_path")
        if template and Path(template).exists():
            sync_worker_compensation(connection, Path(template))
        cost_workbooks = sorted(
            path for path in ROOT.glob("*.xlsx")
            if "cost code" in path.name.casefold()
        )
        if cost_workbooks:
            sync_cost_centers(connection, cost_workbooks[0])


def migrate_database(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(work_days)")
    }
    additions = {
        "start_time": "TEXT NOT NULL DEFAULT ''",
        "end_time": "TEXT NOT NULL DEFAULT ''",
        "work_kind": "TEXT NOT NULL DEFAULT 'None'",
        "cost_center_id": "TEXT NOT NULL DEFAULT ''",
        "cost_center_name": "TEXT NOT NULL DEFAULT ''",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE work_days ADD COLUMN {name} {declaration}")
    connection.execute(
        """
        UPDATE work_days
        SET start_time=CASE WHEN start_time='' THEN '08:30' ELSE start_time END,
            end_time=CASE WHEN end_time='' THEN '16:30' ELSE end_time END,
            work_kind=CASE WHEN work_kind='' THEN 'None' ELSE work_kind END
        WHERE status='worked'
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO work_day_cost_centers(
            work_day_id, cost_center_id, cost_center_name, display_order
        )
        SELECT id, cost_center_id, cost_center_name, 1
        FROM work_days
        WHERE cost_center_id<>'' AND cost_center_name<>''
        """
    )


def sync_cost_centers(connection: sqlite3.Connection, workbook_path: Path) -> None:
    centers = read_cost_centers(workbook_path)
    if not centers:
        return
    connection.execute("DELETE FROM cost_centers")
    connection.executemany(
        "INSERT INTO cost_centers(id, name, display_order) VALUES(?, ?, ?)",
        [
            (center["id"], center["name"], index)
            for index, center in enumerate(centers, start=1)
        ],
    )
    setting(connection, "cost_center_path", str(workbook_path))


def sync_worker_compensation(connection: sqlite3.Connection, workbook_path: Path) -> None:
    for item in read_worker_information(workbook_path):
        worker = worker_for_name(connection, item["name"], create=False)
        if not worker:
            continue
        connection.execute(
            """
            INSERT INTO worker_compensation(
                worker_id, daily_rate, pay_schedule, payment_method, source_name
            ) VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                daily_rate=COALESCE(worker_compensation.daily_rate, excluded.daily_rate),
                pay_schedule=excluded.pay_schedule,
                payment_method=excluded.payment_method,
                source_name=excluded.source_name,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                worker["id"],
                item["daily_rate"],
                item["pay_schedule"],
                item["payment_method"],
                item["name"],
            ),
        )


def pay_period(month: str, half: str) -> tuple[date, date]:
    year, month_number = (int(part) for part in month.split("-", 1))
    if half == "1":
        return date(year, month_number, 1), date(year, month_number, 15)
    last_day = calendar.monthrange(year, month_number)[1]
    return date(year, month_number, 16), date(year, month_number, last_day)


def allocate_location_hours(total_hours: float, locations: list[dict]) -> list[dict]:
    """Keep explicit hours and evenly divide the unassigned remainder."""
    if not locations:
        return []
    specified_total = sum(
        float(item["hours"]) for item in locations if item.get("hours") is not None
    )
    unspecified = [item for item in locations if item.get("hours") is None]
    divided = max(float(total_hours) - specified_total, 0) / len(unspecified) if unspecified else 0
    return [
        {
            "name": item["name"],
            "hours": round(float(item["hours"]) if item.get("hours") is not None else divided, 2),
        }
        for item in locations
    ]


def work_day_allocations(
    connection: sqlite3.Connection,
    start: str,
    end: str,
    worker_id: int | None = None,
) -> list[dict]:
    params: list[object] = [start, end]
    worker_filter = ""
    if worker_id is not None:
        worker_filter = " AND d.worker_id=?"
        params.append(worker_id)
    rows = connection.execute(
        """
        SELECT d.id, d.worker_id, d.work_date, COALESCE(d.total_hours, 8) total_hours,
               w.name worker_name
        FROM work_days d JOIN workers w ON w.id=d.worker_id
        WHERE d.status='worked' AND d.work_date BETWEEN ? AND ?
        """ + worker_filter + " ORDER BY d.work_date, w.display_order, w.name",
        params,
    ).fetchall()
    locations_by_day: dict[int, list[dict]] = {}
    for item in connection.execute(
        """
        SELECT l.work_day_id, l.name, l.hours
        FROM work_locations l JOIN work_days d ON d.id=l.work_day_id
        WHERE d.status='worked' AND d.work_date BETWEEN ? AND ?
        """ + worker_filter + " ORDER BY l.id",
        params,
    ):
        locations_by_day.setdefault(item["work_day_id"], []).append(
            {"name": item["name"], "hours": item["hours"]}
        )
    centers_by_day: dict[int, list[dict]] = {}
    for item in connection.execute(
        """
        SELECT a.work_day_id, a.cost_center_id, a.cost_center_name
        FROM work_day_cost_centers a JOIN work_days d ON d.id=a.work_day_id
        WHERE d.status='worked' AND d.work_date BETWEEN ? AND ?
        """ + worker_filter + " ORDER BY a.display_order, a.cost_center_name",
        params,
    ):
        centers_by_day.setdefault(item["work_day_id"], []).append(
            {"id": item["cost_center_id"], "name": item["cost_center_name"]}
        )
    output = []
    for row in rows:
        total_hours = float(row["total_hours"] or 0)
        locations = locations_by_day.get(row["id"], [])
        centers = centers_by_day.get(row["id"], [])
        center_hours = round(total_hours / len(centers), 2) if centers else 0
        output.append(
            {
                "work_day_id": row["id"],
                "worker_id": row["worker_id"],
                "worker_name": row["worker_name"],
                "date": row["work_date"],
                "total_hours": total_hours,
                "locations": allocate_location_hours(total_hours, locations),
                "cost_centers": [
                    {**center, "hours": center_hours} for center in centers
                ],
            }
        )
    return output


def aggregate_allocations(days: list[dict], field: str) -> list[dict]:
    grouped: dict[str, dict] = {}
    for day in days:
        for item in day[field]:
            key = item.get("id") or item["name"].casefold()
            aggregate = grouped.setdefault(
                key,
                {
                    "id": item.get("id", ""),
                    "name": item["name"],
                    "hours": 0.0,
                    "dates": set(),
                    "worker_ids": set(),
                },
            )
            aggregate["hours"] += float(item["hours"])
            aggregate["dates"].add(day["date"])
            aggregate["worker_ids"].add(day["worker_id"])
    result = []
    for item in grouped.values():
        dates = sorted(item.pop("dates"))
        worker_ids = item.pop("worker_ids")
        item.update(
            {
                "hours": round(item["hours"], 2),
                "days": len(dates),
                "first_date": dates[0],
                "last_date": dates[-1],
                "worker_count": len(worker_ids),
            }
        )
        result.append(item)
    return sorted(result, key=lambda item: (-item["hours"], item["name"].casefold()))


def worker_for_name(
    connection: sqlite3.Connection,
    name: str,
    area: str = "",
    nickname: str = "",
    create: bool = True,
    occurrence: int = 1,
) -> sqlite3.Row | None:
    cleaned = normalize_space(name)
    normalized_base = normalize_name(cleaned)
    if not normalized_base:
        return None
    alias_key = normalized_base if occurrence == 1 else f"{normalized_base}#{occurrence}"
    row = connection.execute(
        "SELECT w.* FROM worker_aliases a JOIN workers w ON w.id=a.worker_id "
        "WHERE a.alias=?",
        (alias_key,),
    ).fetchone()
    if row:
        if (area and not row["area"]) or (nickname and not row["nickname"]):
            connection.execute(
                "UPDATE workers SET area=CASE WHEN area='' THEN ? ELSE area END, "
                "nickname=CASE WHEN nickname='' THEN ? ELSE nickname END WHERE id=?",
                (area, nickname, row["id"]),
            )
        return connection.execute("SELECT * FROM workers WHERE id=?", (row["id"],)).fetchone()

    # Merge only very close spelling variants. Lower-confidence cases remain
    # separate and visible so the user can review them.
    candidates = connection.execute(
        "SELECT * FROM workers WHERE name_occurrence=1"
    ).fetchall()
    best = None
    best_score = 0.0
    if occurrence == 1:
        for candidate in candidates:
            score = SequenceMatcher(
                None, normalized_base, normalize_name(candidate["workbook_name"])
            ).ratio()
            if score > best_score:
                best, best_score = candidate, score
    if occurrence == 1 and best is not None and best_score >= 0.92:
        connection.execute(
            "INSERT OR IGNORE INTO worker_aliases(alias, worker_id) VALUES(?, ?)",
            (alias_key, best["id"]),
        )
        return best
    if not create:
        return None

    order = connection.execute("SELECT COALESCE(MAX(display_order), 0)+1 FROM workers").fetchone()[0]
    display_name = cleaned if occurrence == 1 else f"{cleaned} ({occurrence})"
    normalized_unique = (
        normalized_base if occurrence == 1 else f"{normalized_base} {occurrence}"
    )
    cursor = connection.execute(
        "INSERT INTO workers(name, normalized_name, workbook_name, name_occurrence, "
        "area, nickname, display_order) VALUES(?, ?, ?, ?, ?, ?, ?)",
        (
            display_name,
            normalized_unique,
            cleaned,
            occurrence,
            area,
            nickname,
            order,
        ),
    )
    connection.execute(
        "INSERT INTO worker_aliases(alias, worker_id) VALUES(?, ?)",
        (alias_key, cursor.lastrowid),
    )
    return connection.execute("SELECT * FROM workers WHERE id=?", (cursor.lastrowid,)).fetchone()


def day_record(connection: sqlite3.Connection, worker_id: int, work_date: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM work_days WHERE worker_id=? AND work_date=?",
        (worker_id, work_date),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["locations"] = [
        dict(item)
        for item in connection.execute(
            "SELECT name, hours FROM work_locations WHERE work_day_id=? ORDER BY id",
            (row["id"],),
        )
    ]
    result["cost_centers"] = [
        {"id": item["cost_center_id"], "name": item["cost_center_name"]}
        for item in connection.execute(
            "SELECT cost_center_id, cost_center_name FROM work_day_cost_centers "
            "WHERE work_day_id=? ORDER BY display_order, cost_center_name",
            (row["id"],),
        )
    ]
    return result


def assigned_cost_centers(connection: sqlite3.Connection, work_day_id: int | None) -> list[dict]:
    if not work_day_id:
        return []
    return [
        {"id": item["cost_center_id"], "name": item["cost_center_name"]}
        for item in connection.execute(
            "SELECT cost_center_id, cost_center_name FROM work_day_cost_centers "
            "WHERE work_day_id=? ORDER BY display_order, cost_center_name",
            (work_day_id,),
        )
    ]


def save_day(
    connection: sqlite3.Connection,
    worker_id: int,
    work_date: str,
    payload: dict,
    source: str,
) -> dict:
    old = day_record(connection, worker_id, work_date)
    status = payload.get("status", "unknown")
    total_hours = payload.get("total_hours")
    if total_hours not in (None, ""):
        total_hours = float(total_hours)
    else:
        total_hours = None
    extra_pay = float(payload.get("extra_pay") or 0)
    start_time = payload.get("start_time", "08:30" if status == "worked" else "")
    end_time = payload.get("end_time", "16:30" if status == "worked" else "")
    work_kind = normalize_space(payload.get("work_kind", "None")) or "None"
    supplied_centers = payload.get("cost_centers")
    if supplied_centers is None:
        legacy_id = normalize_space(payload.get("cost_center_id", ""))
        legacy_name = normalize_space(payload.get("cost_center_name", ""))
        if legacy_id or legacy_name:
            supplied_centers = [{"id": legacy_id, "name": legacy_name}]
        elif source != "app" and old:
            supplied_centers = old.get("cost_centers", [])
        else:
            supplied_centers = []
    assigned_centers = []
    seen_center_ids = set()
    for supplied in supplied_centers:
        supplied_id = normalize_space(supplied.get("id", ""))
        supplied_name = normalize_space(supplied.get("name", ""))
        if supplied_id:
            center = connection.execute(
                "SELECT id, name FROM cost_centers WHERE id=?", (supplied_id,)
            ).fetchone()
        elif supplied_name:
            center = connection.execute(
                "SELECT id, name FROM cost_centers WHERE name=? COLLATE NOCASE LIMIT 1",
                (supplied_name,),
            ).fetchone()
        else:
            continue
        if not center:
            raise ValueError(f"Unknown cost center {supplied_id or supplied_name}.")
        if center["id"] in seen_center_ids:
            continue
        assigned_centers.append({"id": center["id"], "name": center["name"]})
        seen_center_ids.add(center["id"])
    cost_center_id = assigned_centers[0]["id"] if assigned_centers else ""
    cost_center_name = assigned_centers[0]["name"] if assigned_centers else ""
    locations = [
        {
            "name": normalize_space(item.get("name", "")),
            "hours": float(item["hours"])
            if item.get("hours") not in (None, "")
            else None,
        }
        for item in payload.get("locations", [])
        if normalize_space(item.get("name", ""))
    ]
    original_text = payload.get("original_text", "")
    if source == "app" or not original_text:
        original_text = format_work_cell(status, total_hours, locations, extra_pay)
    connection.execute(
        """
        INSERT INTO work_days(
            worker_id, work_date, status, total_hours, extra_pay, start_time,
            end_time, work_kind, cost_center_id, cost_center_name, original_text,
            notes, source, confidence, warning, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(worker_id, work_date) DO UPDATE SET
            status=excluded.status, total_hours=excluded.total_hours,
            extra_pay=excluded.extra_pay, original_text=excluded.original_text,
            start_time=excluded.start_time, end_time=excluded.end_time,
            work_kind=excluded.work_kind,
            cost_center_id=excluded.cost_center_id,
            cost_center_name=excluded.cost_center_name,
            notes=excluded.notes, source=excluded.source,
            confidence=excluded.confidence, warning=excluded.warning,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            worker_id,
            work_date,
            status,
            total_hours,
            extra_pay,
            start_time,
            end_time,
            work_kind,
            cost_center_id,
            cost_center_name,
            original_text,
            payload.get("notes", ""),
            source,
            payload.get("confidence", "high"),
            payload.get("warning"),
        ),
    )
    work_day_id = connection.execute(
        "SELECT id FROM work_days WHERE worker_id=? AND work_date=?",
        (worker_id, work_date),
    ).fetchone()["id"]
    connection.execute("DELETE FROM work_locations WHERE work_day_id=?", (work_day_id,))
    connection.executemany(
        "INSERT INTO work_locations(work_day_id, name, hours) VALUES(?, ?, ?)",
        [(work_day_id, item["name"], item["hours"]) for item in locations],
    )
    connection.execute(
        "DELETE FROM work_day_cost_centers WHERE work_day_id=?", (work_day_id,)
    )
    connection.executemany(
        "INSERT INTO work_day_cost_centers("
        "work_day_id, cost_center_id, cost_center_name, display_order"
        ") VALUES(?, ?, ?, ?)",
        [
            (work_day_id, center["id"], center["name"], index)
            for index, center in enumerate(assigned_centers, start=1)
        ],
    )
    new = day_record(connection, worker_id, work_date)
    connection.execute(
        "INSERT INTO audit_log(worker_id, work_date, action, old_json, new_json, source) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (
            worker_id,
            work_date,
            "update" if old else "create",
            json.dumps(old, default=str) if old else None,
            json.dumps(new, default=str),
            source,
        ),
    )
    return new


def import_baseline(connection: sqlite3.Connection, path: Path, year: int) -> None:
    workbook = read_workbook(path, year)
    imported = 0
    review = 0
    for sheet in workbook["sheets"]:
        name_occurrences: dict[str, int] = {}
        for worker_data in sheet["workers"]:
            normalized = normalize_name(worker_data["name"])
            name_occurrences[normalized] = name_occurrences.get(normalized, 0) + 1
            occurrence = name_occurrences[normalized]
            worker = worker_for_name(
                connection,
                worker_data["name"],
                worker_data["area"],
                worker_data["nickname"],
                occurrence=occurrence,
            )
            if not worker:
                continue
            for day in worker_data["days"]:
                if not normalize_space(day["value"]):
                    continue
                parsed = parse_work_cell(day["value"]).to_dict()
                save_day(connection, worker["id"], day["date"], parsed, "baseline")
                imported += 1
                review += parsed["confidence"] == "low"

    # The latest half-month tab is the workbook's current roster. Historical
    # workers stay searchable but do not clutter today's entry screen.
    if workbook["sheets"]:
        connection.execute("UPDATE workers SET active=0")
        name_occurrences = {}
        for worker_data in workbook["sheets"][-1]["workers"]:
            normalized = normalize_name(worker_data["name"])
            name_occurrences[normalized] = name_occurrences.get(normalized, 0) + 1
            worker = worker_for_name(
                connection,
                worker_data["name"],
                create=False,
                occurrence=name_occurrences[normalized],
            )
            if worker:
                connection.execute("UPDATE workers SET active=1 WHERE id=?", (worker["id"],))

    stored = UPLOADS / path.name
    if path.resolve() != stored.resolve():
        shutil.copy2(path, stored)
    cursor = connection.execute(
        "INSERT INTO imports(filename, stored_path, workbook_year, status, added_count, review_count) "
        "VALUES(?, ?, ?, 'applied', ?, ?)",
        (path.name, str(stored), year, imported, review),
    )
    setting(connection, "template_path", str(stored))
    setting(connection, "workbook_year", str(year))
    setting(connection, "baseline_import_id", str(cursor.lastrowid))


def json_response(handler: SimpleHTTPRequestHandler, payload: object, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    return json.loads(handler.rfile.read(length) or b"{}")


def query_value(query: dict, key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def parse_uploaded_file(handler: SimpleHTTPRequestHandler) -> tuple[str, bytes, dict]:
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length)
    content_type = handler.headers.get("Content-Type", "")
    message = BytesParser(policy=default).parsebytes(
        (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode()
        + body
    )
    fields = {}
    filename = ""
    file_bytes = b""
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        name = name_match.group(1) if name_match else ""
        if part.get_filename():
            filename = Path(part.get_filename()).name
            file_bytes = part.get_payload(decode=True)
        elif name:
            fields[name] = part.get_content().strip()
    return filename, file_bytes, fields


def serialize_proposal(parsed: dict, worker_name: str) -> dict:
    return {
        "worker_name": worker_name,
        "status": parsed["status"],
        "total_hours": parsed["total_hours"],
        "extra_pay": parsed["extra_pay"],
        "locations": parsed["locations"],
        "original_text": parsed["original_text"],
        "notes": "",
        "confidence": parsed["confidence"],
        "warning": parsed["warning"],
    }


class WorklogHandler(SimpleHTTPRequestHandler):
    server_version = "Worklog/1.0"

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write(
            f"[{self.log_date_time_string()}] {self.address_string()} {format % args}\n"
        )

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self.handle_api_get(parsed.path, parse_qs(parsed.query))
            else:
                self.serve_static(parsed.path)
        except Exception as exc:
            traceback.print_exc()
            json_response(self, {"error": str(exc)}, 500)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            return
        path = "/index.html" if parsed.path in ("", "/") else parsed.path
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            self.handle_api_post(parsed.path, parse_qs(parsed.query))
        except ValueError as exc:
            json_response(self, {"error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            json_response(self, {"error": str(exc)}, 500)

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self.send_error(404)
            return
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def handle_api_get(self, path: str, query: dict) -> None:
        if path == "/api/bootstrap":
            with connect() as connection:
                workers = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT id, name, area, nickname, active FROM workers "
                        "ORDER BY active DESC, display_order, name"
                    )
                ]
                cost_centers = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT id, name FROM cost_centers ORDER BY display_order, name"
                    )
                ]
                locations = [
                    row["name"]
                    for row in connection.execute(
                        "SELECT MIN(name) name FROM work_locations "
                        "WHERE TRIM(name)<>'' GROUP BY LOWER(TRIM(name)) ORDER BY name"
                    )
                ]
                review_count = connection.execute(
                    "SELECT COUNT(*) FROM work_days WHERE confidence='low'"
                ).fetchone()[0]
                last_date = connection.execute(
                    "SELECT MAX(work_date) FROM work_days"
                ).fetchone()[0]
                json_response(
                    self,
                    {
                        "workers": workers,
                        "cost_centers": cost_centers,
                        "locations": locations,
                        "review_count": review_count,
                        "last_recorded_date": last_date,
                        "workbook_year": int(
                            setting(connection, "workbook_year") or date.today().year
                        ),
                    },
                )
            return

        if path == "/api/summary":
            end = query_value(query, "to", date.today().isoformat())
            start = query_value(query, "from", (date.today() - timedelta(days=30)).isoformat())
            worker_id = query_value(query, "worker_id")
            params: list[object] = [start, end]
            where = "d.work_date BETWEEN ? AND ?"
            if worker_id:
                where += " AND d.worker_id=?"
                params.append(int(worker_id))
            with connect() as connection:
                totals = connection.execute(
                    f"""
                    SELECT COALESCE(SUM(CASE WHEN d.status='worked' THEN d.total_hours ELSE 0 END),0) hours,
                           COUNT(DISTINCT CASE WHEN d.status='worked' THEN d.worker_id END) active_workers,
                           COUNT(CASE WHEN d.status='worked' THEN 1 END) worked_days,
                           COUNT(CASE WHEN d.status='off' THEN 1 END) off_days,
                           COALESCE(SUM(d.extra_pay),0) extra_pay
                    FROM work_days d WHERE {where}
                    """,
                    params,
                ).fetchone()
                records = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT d.id, d.work_date, d.status, d.total_hours, d.extra_pay,
                               d.start_time, d.end_time, d.work_kind,
                               d.cost_center_id, d.cost_center_name,
                               d.original_text, d.notes, d.confidence, d.warning,
                               w.id worker_id, w.name worker_name,
                               GROUP_CONCAT(l.name, ' • ') locations
                        FROM work_days d
                        JOIN workers w ON w.id=d.worker_id
                        LEFT JOIN work_locations l ON l.work_day_id=d.id
                        WHERE {where}
                        GROUP BY d.id
                        ORDER BY d.work_date DESC, w.display_order, w.name
                        LIMIT 500
                        """,
                        params,
                    )
                ]
                for item in records:
                    item["cost_centers"] = assigned_cost_centers(connection, item["id"])
                daily = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT d.work_date date,
                               ROUND(SUM(CASE WHEN d.status='worked' THEN d.total_hours ELSE 0 END),2) hours
                        FROM work_days d WHERE {where}
                        GROUP BY d.work_date ORDER BY d.work_date
                        """,
                        params,
                    )
                ]
                json_response(
                    self,
                    {
                        "range": {"from": start, "to": end},
                        "totals": dict(totals),
                        "records": records,
                        "daily": daily,
                    },
                )
            return

        if path == "/api/payroll/worker-detail":
            worker_id = int(query_value(query, "worker_id", "0"))
            selected_month = query_value(query, "month", date.today().strftime("%Y-%m"))
            half = query_value(query, "half", "1" if date.today().day <= 15 else "2")
            start_day, end_day = pay_period(selected_month, half)
            with connect() as connection:
                worker = connection.execute(
                    "SELECT id, name FROM workers WHERE id=?", (worker_id,)
                ).fetchone()
                if not worker:
                    raise ValueError("Choose a valid worker.")
                selected_days = work_day_allocations(
                    connection, start_day.isoformat(), end_day.isoformat(), worker_id
                )
                locations = aggregate_allocations(selected_days, "locations")
                centers = aggregate_allocations(selected_days, "cost_centers")
                all_days = work_day_allocations(
                    connection, start_day.isoformat(), end_day.isoformat()
                )
                center_counts = {
                    item["id"]: item["worker_count"]
                    for item in aggregate_allocations(all_days, "cost_centers")
                }
                for center in centers:
                    center["worker_count"] = center_counts.get(center["id"], 0)
                json_response(
                    self,
                    {
                        "worker": dict(worker),
                        "period": {
                            "from": start_day.isoformat(),
                            "to": end_day.isoformat(),
                            "month": selected_month,
                            "half": half,
                        },
                        "totals": {
                            "hours": round(sum(day["total_hours"] for day in selected_days), 2),
                            "days": len(selected_days),
                        },
                        "locations": locations,
                        "cost_centers": centers,
                    },
                )
            return

        if path == "/api/location-detail":
            start = date.fromisoformat(query_value(query, "from")).isoformat()
            end = date.fromisoformat(query_value(query, "to")).isoformat()
            if end < start:
                raise ValueError("The end date must be after the start date.")
            requested = normalize_space(query_value(query, "location"))
            if not requested:
                raise ValueError("Choose a location.")
            with connect() as connection:
                matched = connection.execute(
                    "SELECT name FROM work_locations WHERE name=? COLLATE NOCASE LIMIT 1",
                    (requested,),
                ).fetchone()
                if not matched:
                    matched = connection.execute(
                        "SELECT name FROM work_locations WHERE name LIKE ? COLLATE NOCASE "
                        "ORDER BY LENGTH(name), name LIMIT 1",
                        (f"%{requested}%",),
                    ).fetchone()
                if not matched:
                    raise ValueError(f"No location matches {requested}.")
                location_name = matched["name"]
                worker_totals: dict[int, dict] = {}
                all_dates = set()
                for day in work_day_allocations(connection, start, end):
                    allocated = [
                        item for item in day["locations"]
                        if item["name"].casefold() == location_name.casefold()
                    ]
                    if not allocated:
                        continue
                    item = worker_totals.setdefault(
                        day["worker_id"],
                        {
                            "worker_id": day["worker_id"],
                            "worker_name": day["worker_name"],
                            "hours": 0.0,
                            "dates": set(),
                        },
                    )
                    item["hours"] += sum(float(part["hours"]) for part in allocated)
                    item["dates"].add(day["date"])
                    all_dates.add(day["date"])
                workers = []
                for item in worker_totals.values():
                    dates = sorted(item.pop("dates"))
                    item.update(
                        {
                            "hours": round(item["hours"], 2),
                            "days": len(dates),
                            "first_date": dates[0],
                            "last_date": dates[-1],
                        }
                    )
                    workers.append(item)
                workers.sort(key=lambda item: (-item["hours"], item["worker_name"].casefold()))
                sorted_dates = sorted(all_dates)
                json_response(
                    self,
                    {
                        "location": location_name,
                        "range": {"from": start, "to": end},
                        "totals": {
                            "workers": len(workers),
                            "hours": round(sum(item["hours"] for item in workers), 2),
                            "days": len(sorted_dates),
                            "first_date": sorted_dates[0] if sorted_dates else None,
                            "last_date": sorted_dates[-1] if sorted_dates else None,
                        },
                        "workers": workers,
                    },
                )
            return

        if path == "/api/payroll":
            selected_month = query_value(query, "month", date.today().strftime("%Y-%m"))
            half = query_value(query, "half", "1" if date.today().day <= 15 else "2")
            start_day, end_day = pay_period(selected_month, half)
            with connect() as connection:
                rows = connection.execute(
                    """
                    SELECT w.id worker_id, w.name worker_name,
                           COUNT(d.id) recorded_days,
                           COUNT(CASE WHEN d.status='worked' THEN 1 END) worked_days,
                           COUNT(CASE WHEN d.status='off' THEN 1 END) off_days,
                           COALESCE(SUM(CASE WHEN d.status='worked' THEN d.total_hours ELSE 0 END),0) hours,
                           COALESCE(SUM(CASE WHEN d.status='worked' AND d.total_hours>8 THEN d.total_hours-8 ELSE 0 END),0) overtime_hours,
                           COALESCE(SUM(d.extra_pay),0) extra_pay,
                           COALESCE(pc.checked,0) checked
                    FROM workers w
                    LEFT JOIN work_days d ON d.worker_id=w.id
                         AND d.work_date BETWEEN ? AND ?
                    LEFT JOIN payroll_checks pc ON pc.worker_id=w.id
                         AND pc.period_start=?
                    GROUP BY w.id
                    HAVING COUNT(d.id)>0
                    ORDER BY w.display_order, w.name
                    """,
                    (start_day.isoformat(), end_day.isoformat(), start_day.isoformat()),
                ).fetchall()
                workers = [dict(row) for row in rows]
                worked = [item for item in workers if item["worked_days"]]
                json_response(
                    self,
                    {
                        "period": {
                            "month": selected_month,
                            "half": half,
                            "from": start_day.isoformat(),
                            "to": end_day.isoformat(),
                        },
                        "totals": {
                            "hours": round(sum(float(item["hours"]) for item in workers), 2),
                            "workers": len(worked),
                            "checked": len([item for item in workers if item["checked"]]),
                        },
                        "workers": workers,
                    },
                )
            return

        if path == "/api/day":
            selected_date = query_value(query, "date", date.today().isoformat())
            with connect() as connection:
                rows = connection.execute(
                    """
                    SELECT w.id worker_id, w.name worker_name, w.area, w.nickname,
                           d.id day_id, d.status, d.total_hours, d.extra_pay,
                           d.start_time, d.end_time, d.work_kind,
                           d.cost_center_id, d.cost_center_name,
                           d.original_text, d.notes, d.confidence, d.warning
                    FROM workers w
                    LEFT JOIN work_days d ON d.worker_id=w.id AND d.work_date=?
                    WHERE w.active=1
                    ORDER BY w.display_order, w.name
                    """,
                    (selected_date,),
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["locations"] = (
                        [
                            dict(location)
                            for location in connection.execute(
                                "SELECT name, hours FROM work_locations WHERE work_day_id=? ORDER BY id",
                                (row["day_id"],),
                            )
                        ]
                        if row["day_id"]
                        else []
                    )
                    item["cost_centers"] = assigned_cost_centers(
                        connection, row["day_id"]
                    )
                    result.append(item)
                json_response(self, {"date": selected_date, "workers": result})
            return

        if path == "/api/worker-month":
            worker_id = int(query_value(query, "worker_id", "0"))
            selected_month = query_value(query, "month", date.today().strftime("%Y-%m"))
            year, month_number = (int(part) for part in selected_month.split("-", 1))
            last_day = calendar.monthrange(year, month_number)[1]
            with connect() as connection:
                worker = connection.execute(
                    "SELECT id, name FROM workers WHERE id=?", (worker_id,)
                ).fetchone()
                if not worker:
                    raise ValueError("Choose a valid worker.")
                days = []
                for day_number in range(1, last_day + 1):
                    work_date = date(year, month_number, day_number).isoformat()
                    record = day_record(connection, worker_id, work_date)
                    if record:
                        days.append(record)
                    else:
                        days.append(
                            {
                                "worker_id": worker_id,
                                "work_date": work_date,
                                "status": "worked",
                                "total_hours": 8,
                                "extra_pay": 0,
                                "start_time": "08:30",
                                "end_time": "16:30",
                                "work_kind": "None",
                                "cost_center_id": "",
                                "cost_center_name": "",
                                "cost_centers": [],
                                "notes": "",
                                "locations": [],
                            }
                        )
                json_response(
                    self,
                    {
                        "worker": dict(worker),
                        "month": selected_month,
                        "days": days,
                    },
                )
            return

        if path == "/api/review":
            with connect() as connection:
                rows = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT d.id, d.work_date, d.original_text, d.status, d.total_hours,
                               d.extra_pay, d.warning, w.name worker_name,
                               GROUP_CONCAT(l.name, ' / ') locations
                        FROM work_days d JOIN workers w ON w.id=d.worker_id
                        LEFT JOIN work_locations l ON l.work_day_id=d.id
                        WHERE d.confidence='low'
                        GROUP BY d.id
                        ORDER BY d.work_date DESC, w.name
                        """
                    )
                ]
                json_response(self, {"items": rows})
            return

        if path == "/api/imports":
            with connect() as connection:
                rows = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM imports ORDER BY id DESC LIMIT 20"
                    )
                ]
                json_response(self, {"imports": rows})
            return

        conflict_match = re.fullmatch(r"/api/imports/(\d+)/conflicts", path)
        if conflict_match:
            import_id = int(conflict_match.group(1))
            with connect() as connection:
                rows = []
                for row in connection.execute(
                    "SELECT * FROM import_conflicts WHERE import_id=? ORDER BY work_date, worker_name",
                    (import_id,),
                ):
                    item = dict(row)
                    item["current"] = json.loads(item.pop("current_json")) if item["current_json"] else None
                    item["proposed"] = json.loads(item.pop("proposed_json"))
                    rows.append(item)
                json_response(self, {"conflicts": rows})
            return

        if path == "/api/export":
            start = query_value(query, "from", f"{date.today().year}-01-01")
            end = query_value(query, "to", date.today().isoformat())
            with connect() as connection:
                template = setting(connection, "template_path")
                year = int(setting(connection, "workbook_year") or start[:4])
                if not template or not Path(template).exists():
                    json_response(self, {"error": "No workbook template is available."}, 400)
                    return
                rows = connection.execute(
                    """
                    SELECT d.*, w.name worker_name, w.workbook_name,
                           w.name_occurrence
                    FROM work_days d JOIN workers w ON w.id=d.worker_id
                    WHERE d.work_date BETWEEN ? AND ?
                    """,
                    (start, end),
                ).fetchall()
                updates = []
                for row in rows:
                    locations = [
                        dict(item)
                        for item in connection.execute(
                            "SELECT name, hours FROM work_locations WHERE work_day_id=? ORDER BY id",
                            (row["id"],),
                        )
                    ]
                    value = row["original_text"] if row["source"] in ("baseline", "import") else format_work_cell(
                        row["status"], row["total_hours"], locations, row["extra_pay"]
                    )
                    updates.append(
                        {
                            "worker_name": row["workbook_name"],
                            "occurrence": row["name_occurrence"],
                            "date": row["work_date"],
                            "value": value,
                        }
                    )
                output = io.BytesIO()
                update_workbook(template, output, updates, year)
                data = output.getvalue()
                filename = f"worker-hours-{start}-to-{end}.xlsx"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            return

        json_response(self, {"error": "Not found"}, 404)

    def handle_api_post(self, path: str, query: dict) -> None:
        if path == "/api/workers":
            payload = read_json(self)
            name = normalize_space(payload.get("name", ""))
            if not name:
                raise ValueError("Worker name is required.")
            with connect() as connection:
                worker = worker_for_name(
                    connection,
                    name,
                    normalize_space(payload.get("area", "")),
                    normalize_space(payload.get("nickname", "")),
                )
                json_response(self, {"worker": dict(worker)}, 201)
            return

        rate_match = re.fullmatch(r"/api/workers/(\d+)/rate", path)
        if rate_match:
            worker_id = int(rate_match.group(1))
            payload = read_json(self)
            daily_rate = float(payload.get("daily_rate"))
            if daily_rate < 0:
                raise ValueError("Daily rate cannot be negative.")
            with connect() as connection:
                connection.execute(
                    """
                    INSERT INTO worker_compensation(worker_id, daily_rate)
                    VALUES(?, ?)
                    ON CONFLICT(worker_id) DO UPDATE SET
                        daily_rate=excluded.daily_rate, updated_at=CURRENT_TIMESTAMP
                    """,
                    (worker_id, daily_rate),
                )
                json_response(self, {"updated": True, "daily_rate": daily_rate})
            return

        if path == "/api/payroll/check":
            payload = read_json(self)
            worker_id = int(payload["worker_id"])
            period_start = date.fromisoformat(payload["period_start"]).isoformat()
            checked = 1 if payload.get("checked") else 0
            with connect() as connection:
                connection.execute(
                    """
                    INSERT INTO payroll_checks(worker_id, period_start, checked, checked_at)
                    VALUES(?, ?, ?, CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                    ON CONFLICT(worker_id, period_start) DO UPDATE SET
                        checked=excluded.checked,
                        checked_at=excluded.checked_at
                    """,
                    (worker_id, period_start, checked, checked),
                )
                json_response(self, {"updated": True, "checked": bool(checked)})
            return

        if path == "/api/day":
            payload = read_json(self)
            selected_date = payload.get("date")
            date.fromisoformat(selected_date)
            records = payload.get("records", [])
            with connect() as connection:
                saved = []
                for record in records:
                    worker_id = int(record["worker_id"])
                    exists = connection.execute(
                        "SELECT 1 FROM workers WHERE id=?", (worker_id,)
                    ).fetchone()
                    if not exists:
                        raise ValueError(f"Unknown worker {worker_id}.")
                    if record.get("status") == "worked" and not any(
                        normalize_space(item.get("name", ""))
                        for item in record.get("locations", [])
                    ):
                        raise ValueError("Every worker marked Worked needs a location.")
                    saved.append(save_day(connection, worker_id, selected_date, record, "app"))
                json_response(self, {"saved": len(saved), "date": selected_date})
            return

        if path == "/api/worker-days":
            payload = read_json(self)
            worker_id = int(payload["worker_id"])
            records = payload.get("records", [])
            with connect() as connection:
                exists = connection.execute(
                    "SELECT 1 FROM workers WHERE id=?", (worker_id,)
                ).fetchone()
                if not exists:
                    raise ValueError("Choose a valid worker.")
                saved = []
                for record in records:
                    work_date = date.fromisoformat(record["date"]).isoformat()
                    if record.get("status") == "worked" and not any(
                        normalize_space(item.get("name", ""))
                        for item in record.get("locations", [])
                    ):
                        raise ValueError(
                            f"A location is required for {work_date}."
                        )
                    saved.append(
                        save_day(connection, worker_id, work_date, record, "app")
                    )
                json_response(self, {"saved": len(saved)})
            return

        if path == "/api/parse":
            payload = read_json(self)
            json_response(self, parse_work_cell(payload.get("text", "")).to_dict())
            return

        if path == "/api/import":
            filename, file_bytes, fields = parse_uploaded_file(self)
            if not filename.lower().endswith((".xlsx", ".xlsm")) or not file_bytes:
                raise ValueError("Choose a valid .xlsx workbook.")
            year = int(fields.get("year") or date.today().year)
            safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            stored = UPLOADS / f"{stamp}-{safe_name}"
            stored.write_bytes(file_bytes)
            workbook = read_workbook(stored, year)
            with connect() as connection:
                import_cursor = connection.execute(
                    "INSERT INTO imports(filename, stored_path, workbook_year, status) "
                    "VALUES(?, ?, ?, 'review')",
                    (filename, str(stored), year),
                )
                import_id = import_cursor.lastrowid
                added = changed = review = 0
                for sheet in workbook["sheets"]:
                    name_occurrences: dict[str, int] = {}
                    for worker_data in sheet["workers"]:
                        normalized = normalize_name(worker_data["name"])
                        name_occurrences[normalized] = name_occurrences.get(normalized, 0) + 1
                        occurrence = name_occurrences[normalized]
                        for day in worker_data["days"]:
                            if not normalize_space(day["value"]):
                                continue
                            parsed_cell = parse_work_cell(day["value"]).to_dict()
                            proposed = serialize_proposal(parsed_cell, worker_data["name"])
                            worker = worker_for_name(
                                connection,
                                worker_data["name"],
                                create=False,
                                occurrence=occurrence,
                            )
                            current = (
                                day_record(connection, worker["id"], day["date"])
                                if worker
                                else None
                            )
                            comparable_current = None
                            if current:
                                comparable_current = {
                                    key: current[key]
                                    for key in (
                                        "status",
                                        "total_hours",
                                        "extra_pay",
                                        "original_text",
                                        "locations",
                                    )
                                }
                            comparable_proposed = {
                                key: proposed[key]
                                for key in (
                                    "status",
                                    "total_hours",
                                    "extra_pay",
                                    "original_text",
                                    "locations",
                                )
                            }
                            if comparable_current == comparable_proposed:
                                continue
                            action = "add" if not current else "change"
                            if parsed_cell["confidence"] == "low":
                                action = "review"
                                review += 1
                            elif current:
                                changed += 1
                            else:
                                added += 1
                            connection.execute(
                                """
                                INSERT INTO import_conflicts(
                                    import_id, worker_name, worker_occurrence, work_date,
                                    current_json, proposed_json, action
                                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    import_id,
                                    worker_data["name"],
                                    occurrence,
                                    day["date"],
                                    json.dumps(comparable_current, ensure_ascii=False),
                                    json.dumps(proposed, ensure_ascii=False),
                                    action,
                                ),
                            )
                connection.execute(
                    "UPDATE imports SET added_count=?, changed_count=?, review_count=? WHERE id=?",
                    (added, changed, review, import_id),
                )
                json_response(
                    self,
                    {
                        "import_id": import_id,
                        "filename": filename,
                        "added": added,
                        "changed": changed,
                        "review": review,
                    },
                    201,
                )
            return

        apply_match = re.fullmatch(r"/api/imports/(\d+)/apply", path)
        if apply_match:
            import_id = int(apply_match.group(1))
            payload = read_json(self)
            accepted = {int(item) for item in payload.get("conflict_ids", [])}
            with connect() as connection:
                imported = connection.execute(
                    "SELECT * FROM imports WHERE id=?", (import_id,)
                ).fetchone()
                if not imported:
                    raise ValueError("Import not found.")
                applied = 0
                for row in connection.execute(
                    "SELECT * FROM import_conflicts WHERE import_id=? AND status='pending'",
                    (import_id,),
                ).fetchall():
                    if row["id"] not in accepted:
                        continue
                    proposed = json.loads(row["proposed_json"])
                    worker = worker_for_name(
                        connection,
                        row["worker_name"],
                        occurrence=row["worker_occurrence"],
                    )
                    save_day(
                        connection,
                        worker["id"],
                        row["work_date"],
                        proposed,
                        f"import:{import_id}",
                    )
                    connection.execute(
                        "UPDATE import_conflicts SET status='applied' WHERE id=?",
                        (row["id"],),
                    )
                    applied += 1
                pending = connection.execute(
                    "SELECT COUNT(*) FROM import_conflicts WHERE import_id=? AND status='pending'",
                    (import_id,),
                ).fetchone()[0]
                connection.execute(
                    "UPDATE imports SET status=? WHERE id=?",
                    ("applied" if pending == 0 else "partial", import_id),
                )
                if applied:
                    setting(connection, "template_path", imported["stored_path"])
                    setting(connection, "workbook_year", str(imported["workbook_year"]))
                json_response(self, {"applied": applied, "pending": pending})
            return

        review_match = re.fullmatch(r"/api/review/(\d+)", path)
        if review_match:
            work_day_id = int(review_match.group(1))
            payload = read_json(self)
            with connect() as connection:
                row = connection.execute(
                    "SELECT worker_id, work_date FROM work_days WHERE id=?",
                    (work_day_id,),
                ).fetchone()
                if not row:
                    raise ValueError("Record not found.")
                payload["confidence"] = "high"
                payload["warning"] = None
                save_day(
                    connection,
                    row["worker_id"],
                    row["work_date"],
                    payload,
                    "review",
                )
                json_response(self, {"updated": True})
            return

        json_response(self, {"error": "Not found"}, 404)


def main() -> None:
    init_database()
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    server = ThreadingHTTPServer(("127.0.0.1", port), WorklogHandler)
    print(f"Speed Construction Worker Schedule is running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
