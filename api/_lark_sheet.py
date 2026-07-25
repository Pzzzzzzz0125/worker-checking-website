from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote

from api._lark import LarkAPIError, lark_api, tenant_access_token
from api._lark_base import (
    bool_value,
    date_value,
    field,
    number_value,
    text_value,
)
from api._lark_drive import drive_folder_token
from api._work_log import compact_number


WORKBOOK_SETTING = "lark_work_schedule"
WORKBOOK_TITLE = "Speed Construction Work Schedule"
WORKER_COLUMN_WIDTH = 190
WORK_CELL_WIDTH = 300
HEADER_ROW_HEIGHT = 40
WORK_CELL_HEIGHT = 120


@dataclass(frozen=True)
class PayPeriod:
    key: str
    title: str
    start: date
    end: date


def _month_end(year: int, month: int) -> int:
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    return (following - date.resolution).day


def pay_period(value: str | date) -> PayPeriod:
    selected = value if isinstance(value, date) else date.fromisoformat(value)
    if selected.day <= 15:
        start = selected.replace(day=1)
        end = selected.replace(day=15)
        half = "01-15"
    else:
        start = selected.replace(day=16)
        end = selected.replace(day=_month_end(selected.year, selected.month))
        half = f"16-{end.day:02d}"
    key = f"{selected.year:04d}-{selected.month:02d}-{1 if selected.day <= 15 else 2}"
    return PayPeriod(
        key=key,
        title=f"{selected.year:04d}-{selected.month:02d} · {half}",
        start=start,
        end=end,
    )


def period_dates(period: PayPeriod) -> list[date]:
    return [
        period.start + (index * date.resolution)
        for index in range((period.end - period.start).days + 1)
    ]


def column_name(number: int) -> str:
    if number < 1:
        raise ValueError("Spreadsheet columns start at one.")
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(65 + remainder) + output
    return output


def worker_profiles(records: list[dict]) -> list[dict]:
    workers = []
    for fallback, record in enumerate(records, start=1):
        key = text_value(field(record, "Worker Key"))
        name = text_value(field(record, "Name"))
        if not key or not name:
            continue
        worker_type = text_value(field(record, "Worker Type")).upper().replace("-", "")
        workers.append(
            {
                "key": key,
                "name": name,
                "type": worker_type if worker_type in {"W2", "1099"} else "1099",
                "active": bool_value(field(record, "Active"), True),
                "order": int(number_value(field(record, "Display Order"), fallback)),
            }
        )
    return sorted(
        workers,
        key=lambda item: (
            not item["active"],
            item["order"],
            item["name"].casefold(),
        ),
    )


def assign_worker_rows(
    workers: list[dict],
    existing: dict[str, Any] | None = None,
    work_rows: list[dict] | None = None,
) -> dict[str, int]:
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for key, raw_row in (existing or {}).items():
        try:
            row = int(raw_row)
        except (TypeError, ValueError):
            continue
        if key and row >= 2 and row not in used:
            mapping[str(key)] = row
            used.add(row)
    next_row = max(used, default=1) + 1
    names = {worker["key"] for worker in workers}
    names.update(
        text_value(row.get("Worker Key"))
        for row in (work_rows or [])
        if text_value(row.get("Worker Key"))
    )
    ordered_keys = [worker["key"] for worker in workers]
    ordered_keys.extend(sorted(names - set(ordered_keys)))
    for key in ordered_keys:
        if key in mapping:
            continue
        while next_row in used:
            next_row += 1
        mapping[key] = next_row
        used.add(next_row)
        next_row += 1
    return mapping


def sheet_cell_text(row: dict) -> str:
    status = text_value(row.get("Status")).upper() or "WORKED"
    normalized = text_value(row.get("Normalized Entry")) or "—"
    total = compact_number(number_value(row.get("Total Hours")))
    regular = compact_number(number_value(row.get("Regular Hours")))
    overtime = compact_number(number_value(row.get("Overtime Hours")))
    extra = compact_number(number_value(row.get("Extra Pay")))
    lines = [
        f"{status} | {normalized}",
        f"TOTAL {total}h | REG {regular}h | OT {overtime}h | EXTRA ${extra}",
    ]
    notes = text_value(row.get("Notes"))
    if notes:
        lines.append(f"NOTE: {' '.join(notes.replace(chr(10), ' ').split())}")
    source = text_value(row.get("Source")) or "unknown"
    confidence = text_value(row.get("Confidence")) or "unknown"
    lines.append(f"SOURCE {source} | CONFIDENCE {confidence}")
    return "\n".join(lines)


def _sheet_id(item: dict) -> str:
    return str(item.get("sheetId") or item.get("sheet_id") or "")


class LarkWorkbook:
    def __init__(self, spreadsheet_token: str, url: str = "") -> None:
        self.token = tenant_access_token()
        self.spreadsheet_token = spreadsheet_token.strip()
        self.url = url.strip()
        if not self.spreadsheet_token:
            raise LarkAPIError("The Lark work-schedule spreadsheet token is missing.")

    @classmethod
    def create(cls) -> tuple["LarkWorkbook", dict]:
        payload = lark_api(
            "POST",
            "/sheets/v3/spreadsheets",
            token=tenant_access_token(),
            body={
                "title": WORKBOOK_TITLE,
                "folder_token": drive_folder_token(),
            },
        )
        spreadsheet = (payload.get("data") or {}).get("spreadsheet") or {}
        spreadsheet_token = str(spreadsheet.get("spreadsheet_token") or "")
        url = str(spreadsheet.get("url") or "")
        if not spreadsheet_token:
            raise LarkAPIError("Lark created the workbook without returning its token.")
        config = {
            "spreadsheet_token": spreadsheet_token,
            "url": url,
            "title": WORKBOOK_TITLE,
            "worker_rows": {},
        }
        return cls(spreadsheet_token, url), config

    def metadata(self) -> dict:
        return lark_api(
            "GET",
            (
                "/sheets/v2/spreadsheets/"
                f"{quote(self.spreadsheet_token, safe='')}/metainfo"
            ),
            token=self.token,
        ).get("data") or {}

    def sheets(self) -> dict[str, str]:
        return {
            str(item.get("title") or ""): _sheet_id(item)
            for item in self.metadata().get("sheets") or []
            if item.get("title") and _sheet_id(item)
        }

    def _update_sheets(self, requests: list[dict]) -> None:
        if not requests:
            return
        lark_api(
            "POST",
            (
                "/sheets/v2/spreadsheets/"
                f"{quote(self.spreadsheet_token, safe='')}/sheets_batch_update"
            ),
            token=self.token,
            body={"requests": requests},
        )

    def ensure_periods(self, periods: list[PayPeriod]) -> dict[str, str]:
        periods = sorted({period.key: period for period in periods}.values(), key=lambda p: p.key)
        if not periods:
            periods = [pay_period(date.today())]
        existing = self.sheets()
        requests: list[dict] = []

        first = periods[0]
        if (
            first.title not in existing
            and len(existing) == 1
            and not re.match(r"^\d{4}-\d{2} · ", next(iter(existing)))
        ):
            current_title, current_id = next(iter(existing.items()))
            requests.append(
                {
                    "updateSheet": {
                        "properties": {
                            "sheetId": current_id,
                            "title": first.title,
                            "frozenRowCount": 1,
                            "frozenColCount": 1,
                        }
                    }
                }
            )
            existing.pop(current_title)
            existing[first.title] = current_id

        for period in periods:
            if period.title in existing:
                continue
            requests.append(
                {
                    "addSheet": {
                        "properties": {
                            "title": period.title,
                        }
                    }
                }
            )
        self._update_sheets(requests)
        current = self.sheets()
        missing = [period.title for period in periods if period.title not in current]
        if missing:
            raise LarkAPIError(
                "Lark did not create every payroll-period worksheet: "
                + ", ".join(missing[:3])
            )
        freeze = [
            {
                "updateSheet": {
                    "properties": {
                        "sheetId": current[period.title],
                        "frozenRowCount": 1,
                        "frozenColCount": 1,
                    }
                }
            }
            for period in periods
        ]
        self._update_sheets(freeze)
        return {period.key: current[period.title] for period in periods}

    def write_range(self, sheet_id: str, cell_range: str, values: list[list[Any]]) -> None:
        lark_api(
            "PUT",
            (
                "/sheets/v2/spreadsheets/"
                f"{quote(self.spreadsheet_token, safe='')}/values"
            ),
            token=self.token,
            body={
                "valueRange": {
                    "range": f"{sheet_id}!{cell_range}",
                    "values": values,
                }
            },
        )

    def write_cells(self, cells: list[tuple[str, str, str]]) -> None:
        if not cells:
            return
        value_ranges = [
            {"range": f"{sheet_id}!{cell}", "values": [[value]]}
            for sheet_id, cell, value in cells
        ]
        for offset in range(0, len(value_ranges), 100):
            lark_api(
                "POST",
                (
                    "/sheets/v2/spreadsheets/"
                    f"{quote(self.spreadsheet_token, safe='')}/values_batch_update"
                ),
                token=self.token,
                body={"valueRanges": value_ranges[offset : offset + 100]},
            )

    def style_range(self, sheet_id: str, cell_range: str, style: dict) -> None:
        lark_api(
            "PUT",
            (
                "/sheets/v2/spreadsheets/"
                f"{quote(self.spreadsheet_token, safe='')}/style"
            ),
            token=self.token,
            body={
                "appendStyle": {
                    "range": f"{sheet_id}!{cell_range}",
                    "style": style,
                }
            },
        )

    def resize_dimension(
        self,
        sheet_id: str,
        dimension: str,
        start_index: int,
        end_index: int,
        fixed_size: int,
    ) -> None:
        if end_index <= start_index:
            return
        lark_api(
            "PUT",
            (
                "/sheets/v2/spreadsheets/"
                f"{quote(self.spreadsheet_token, safe='')}/dimension_range"
            ),
            token=self.token,
            body={
                "dimension": {
                    "sheetId": sheet_id,
                    "majorDimension": dimension,
                    "startIndex": start_index,
                    "endIndex": end_index,
                },
                "dimensionProperties": {
                    "visible": True,
                    "fixedSize": fixed_size,
                },
            },
        )

    def apply_readable_layout(
        self,
        sheet_id: str,
        date_columns: int,
        worker_rows: int,
    ) -> None:
        self.resize_dimension(
            sheet_id, "COLUMNS", 0, 1, WORKER_COLUMN_WIDTH,
        )
        self.resize_dimension(
            sheet_id, "COLUMNS", 1, date_columns + 1, WORK_CELL_WIDTH,
        )
        self.resize_dimension(
            sheet_id, "ROWS", 0, 1, HEADER_ROW_HEIGHT,
        )
        self.resize_dimension(
            sheet_id, "ROWS", 1, max(worker_rows, 2), WORK_CELL_HEIGHT,
        )

    def initialize(
        self,
        workers: list[dict],
        work_rows: list[dict],
        config: dict,
    ) -> dict:
        worker_rows = assign_worker_rows(
            workers,
            config.get("worker_rows") if isinstance(config, dict) else {},
            work_rows,
        )
        dates = [
            date_value(row.get("Work Date"))
            for row in work_rows
            if date_value(row.get("Work Date"))
        ]
        periods = sorted(
            {pay_period(value).key: pay_period(value) for value in dates}.values(),
            key=lambda item: item.key,
        )
        if not periods:
            periods = [pay_period(date.today())]
        tabs = self.ensure_periods(periods)
        worker_by_key = {worker["key"]: worker for worker in workers}
        historical_names = {
            text_value(row.get("Worker Key")): text_value(row.get("Worker Name"))
            for row in work_rows
            if text_value(row.get("Worker Key")) and text_value(row.get("Worker Name"))
        }
        work_by_cell = {
            (text_value(row.get("Worker Key")), date_value(row.get("Work Date"))): row
            for row in work_rows
            if text_value(row.get("Worker Key")) and date_value(row.get("Work Date"))
        }
        max_row = max(worker_rows.values(), default=1)

        for period in periods:
            dates_in_period = period_dates(period)
            values = [[""] * (len(dates_in_period) + 1) for _ in range(max_row)]
            values[0] = ["Worker"] + [value.strftime("%m/%d") for value in dates_in_period]
            for worker_key, row_number in worker_rows.items():
                worker = worker_by_key.get(worker_key, {})
                values[row_number - 1][0] = (
                    worker.get("name")
                    or historical_names.get(worker_key)
                    or worker_key
                )
                for index, work_date in enumerate(dates_in_period, start=1):
                    work_row = work_by_cell.get((worker_key, work_date.isoformat()))
                    if work_row:
                        values[row_number - 1][index] = sheet_cell_text(work_row)
            last_column = column_name(len(dates_in_period) + 1)
            sheet_id = tabs[period.key]
            self.write_range(
                sheet_id,
                f"A1:{last_column}{max_row}",
                values,
            )
            self.style_range(
                sheet_id,
                f"A1:{last_column}1",
                {
                    "font": {"bold": True},
                    "foreColor": "#FFFFFF",
                    "backColor": "#17324D",
                    "hAlign": 1,
                    "vAlign": 1,
                    "borderType": "FULL_BORDER",
                    "borderColor": "#E2E8F0",
                    "clean": False,
                },
            )
            self.style_range(
                sheet_id,
                f"A2:{last_column}{max_row}",
                {
                    "vAlign": 0,
                    "borderType": "FULL_BORDER",
                    "borderColor": "#E2E8F0",
                    "clean": False,
                },
            )
            self.apply_readable_layout(
                sheet_id,
                len(dates_in_period),
                max_row,
            )

        config["worker_rows"] = worker_rows
        return {
            "periods": len(periods),
            "workers": len(worker_rows),
            "work_cells": len(work_by_cell),
            "worker_rows": worker_rows,
        }

    def sync_work_rows(
        self,
        workers: list[dict],
        work_rows: list[dict],
        deleted_day_keys: list[str],
        config: dict,
    ) -> dict:
        worker_rows = assign_worker_rows(
            workers,
            config.get("worker_rows") if isinstance(config, dict) else {},
            work_rows,
        )
        requested_dates = [
            date_value(row.get("Work Date"))
            for row in work_rows
            if date_value(row.get("Work Date"))
        ]
        for day_key in deleted_day_keys:
            possible = day_key.rsplit("|", 1)[-1]
            if len(possible) == 10:
                requested_dates.append(possible)
        periods = list(
            {pay_period(value).key: pay_period(value) for value in requested_dates}.values()
        )
        tabs = self.ensure_periods(periods)
        cells: list[tuple[str, str, str]] = []
        by_key = {worker["key"]: worker for worker in workers}
        for period in periods:
            sheet_id = tabs[period.key]
            cells.append((sheet_id, "A1", "Worker"))
            for index, work_date in enumerate(period_dates(period), start=2):
                cells.append(
                    (
                        sheet_id,
                        f"{column_name(index)}1",
                        work_date.strftime("%m/%d"),
                    )
                )
            cells.extend(
                (
                    sheet_id,
                    f"A{row_number}",
                    by_key.get(worker_key, {}).get("name") or worker_key,
                )
                for worker_key, row_number in worker_rows.items()
            )
        for row in work_rows:
            worker_key = text_value(row.get("Worker Key"))
            work_date = date_value(row.get("Work Date"))
            if worker_key not in worker_rows or not work_date:
                continue
            period = pay_period(work_date)
            column = (date.fromisoformat(work_date) - period.start).days + 2
            cells.append(
                (
                    tabs[period.key],
                    f"{column_name(column)}{worker_rows[worker_key]}",
                    sheet_cell_text(row),
                )
            )
        for day_key in deleted_day_keys:
            worker_key, _, work_date = day_key.rpartition("|")
            if worker_key not in worker_rows or len(work_date) != 10:
                continue
            period = pay_period(work_date)
            column = (date.fromisoformat(work_date) - period.start).days + 2
            cells.append(
                (
                    tabs[period.key],
                    f"{column_name(column)}{worker_rows[worker_key]}",
                    "",
                )
            )
        self.write_cells(cells)
        config["worker_rows"] = worker_rows
        return {"updated_cells": len(cells), "worker_rows": worker_rows}

    def sync_workers(self, workers: list[dict], config: dict) -> dict:
        worker_rows = assign_worker_rows(
            workers,
            config.get("worker_rows") if isinstance(config, dict) else {},
        )
        sheets = self.sheets()
        by_key = {worker["key"]: worker for worker in workers}
        cells = [
            (sheet_id, f"A{row}", by_key.get(key, {}).get("name") or key)
            for sheet_id in sheets.values()
            for key, row in worker_rows.items()
        ]
        self.write_cells(cells)
        config["worker_rows"] = worker_rows
        return {"updated_cells": len(cells), "worker_rows": worker_rows}


def configured_workbook(database) -> tuple[LarkWorkbook, dict] | None:
    configured_token = os.environ.get("LARK_WORKBOOK_TOKEN", "").strip()
    config = database.get_setting(WORKBOOK_SETTING) or {}
    spreadsheet_token = configured_token or str(config.get("spreadsheet_token") or "")
    if not spreadsheet_token:
        return None
    url = str(config.get("url") or "")
    return LarkWorkbook(spreadsheet_token, url), config
