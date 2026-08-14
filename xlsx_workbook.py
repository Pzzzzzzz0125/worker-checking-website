"""Small XLSX reader/updater tailored to the worker workbook.

It intentionally uses only Python's standard library.  Existing workbook files
are updated as ZIP packages so unrelated reference sheets and formatting remain
intact.
"""

from __future__ import annotations

import calendar
import io
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from posixpath import join as posix_join, normpath
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XR_NS = "http://schemas.microsoft.com/office/spreadsheetml/2014/revision"
NS = {"m": MAIN_NS, "r": REL_NS, "pr": PKG_REL_NS}
ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)


def column_number(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference.upper())
    if not letters:
        return 0
    result = 0
    for letter in letters.group(1):
        result = result * 26 + ord(letter) - 64
    return result


def column_letters(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", NS))
    value = cell.find("m:v", NS)
    if value is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value.text or 0)]
        except (IndexError, ValueError):
            return ""
    return value.text or ""


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", NS))
        for item in root.findall("m:si", NS)
    ]


def workbook_sheets(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.attrib["Id"]: item.attrib["Target"].lstrip("/")
        for item in relationships
    }
    sheets = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
        target = targets[relationship_id]
        if target.startswith("/"):
            sheet_path = normpath(target.lstrip("/"))
        elif target.startswith("xl/"):
            sheet_path = normpath(target)
        else:
            sheet_path = normpath(posix_join("xl", target))
        sheets.append((sheet.attrib["name"], sheet_path))
    return sheets


def sheet_rows(
    archive: ZipFile, path: str, shared_strings: list[str]
) -> list[dict[int, str]]:
    root = ET.fromstring(archive.read(path))
    output = []
    for row in root.findall("m:sheetData/m:row", NS):
        values: dict[int, str] = {}
        for cell in row.findall("m:c", NS):
            values[column_number(cell.attrib.get("r", ""))] = cell_value(
                cell, shared_strings
            )
        output.append(values)
    return output


def read_payroll_workbook(path: str | Path, year: int) -> list[dict]:
    """Read the half-month payroll sheets, including the red/black worker marker."""
    output = []
    with ZipFile(path) as archive:
        shared = _shared_strings(archive)
        style_colors = {}
        if "xl/styles.xml" in archive.namelist():
            styles = ET.fromstring(archive.read("xl/styles.xml"))
            fonts = styles.findall("m:fonts/m:font", NS)
            for idx, xf in enumerate(styles.findall("m:cellXfs/m:xf", NS)):
                font_id = int(xf.attrib.get("fontId", 0))
                colors = fonts[font_id].findall("m:color", NS) if font_id < len(fonts) else []
                style_colors[str(idx)] = (colors[0].attrib.get("rgb", "") if colors else "").upper()
        for sheet_name, sheet_path in workbook_sheets(archive):
            match = re.match(r"\s*(\d{1,2})\.(\d{1,2})\s+to\s+(\d{1,2})\.(\d{1,2})", sheet_name)
            if not match:
                continue
            sm, sd, em, ed = map(int, match.groups())
            start = date(year, sm, sd).isoformat()
            end = date(year, em, ed).isoformat()
            rows = sheet_rows(archive, sheet_path, shared)
            if not rows:
                continue
            headers = {normalize_sheet_name(v).casefold(): c for c, v in rows[0].items()}
            name_col = next((c for k, c in headers.items() if "worker" in k or k == "name"), 1)
            rate_col = next((c for k, c in headers.items() if "daily" in k and "salary" in k), None)
            ot_col = next((c for k, c in headers.items() if k in ("overtime", "ot hours", "overtime hours")), None)
            notes_col = next((c for k, c in headers.items() if "note" in k), None)
            # Re-read styles for the worker-name cells; red denotes 1099 in this workbook.
            xml = ET.fromstring(archive.read(sheet_path))
            xml_rows = xml.findall("m:sheetData/m:row", NS)
            for index, row in enumerate(rows[1:]):
                name = normalize_sheet_name(row.get(name_col, ""))
                if not name:
                    continue
                style = ""
                if index + 1 < len(xml_rows):
                    cell = next((c for c in xml_rows[index + 1].findall("m:c", NS) if column_number(c.attrib.get("r", "")) == name_col), None)
                    style = cell.attrib.get("s", "") if cell is not None else ""
                # Speed Payroll convention: red names are W2; black names are 1099.
                worker_type = "W2" if style_colors.get(style, "").endswith("F54A45") else "1099"
                def number(value):
                    try: return float(str(value).replace(",", "").replace("$", ""))
                    except (TypeError, ValueError): return 0.0
                output.append({"name": name, "from": start, "to": end, "worker_type": worker_type,
                               "daily_rate": number(row.get(rate_col, 0)) if rate_col else 0.0,
                               "overtime_hours": number(row.get(ot_col, 0)) if ot_col else 0.0,
                               "notes": normalize_sheet_name(row.get(notes_col, "")) if notes_col else ""})
    return output


def parse_header_date(header: str, year: int) -> date | None:
    match = re.search(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)", header or "")
    if not match:
        return None
    try:
        return date(year, int(match.group(1)), int(match.group(2)))
    except ValueError:
        return None


def normalize_sheet_name(value: str) -> str:
    return " ".join((value or "").split())


def read_workbook(path: str | Path, year: int) -> dict:
    """Read half-month work sheets and retain all visible row metadata."""
    result = {"sheets": [], "source": str(path)}
    with ZipFile(path) as archive:
        shared = _shared_strings(archive)
        for name, sheet_path in workbook_sheets(archive):
            if not re.search(
                r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
                r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
                r"nov(?:ember)?|dec(?:ember)?)\s+\d+\s*-\s*\d+",
                normalize_sheet_name(name),
                re.IGNORECASE,
            ):
                continue
            rows = sheet_rows(archive, sheet_path, shared)
            if not rows:
                continue
            header = rows[0]
            date_columns = {
                column: parsed
                for column, value in header.items()
                if column >= 4 and (parsed := parse_header_date(value, year))
            }
            if not date_columns:
                continue
            workers = []
            for index, row in enumerate(rows[1:], start=2):
                worker_name = (row.get(1) or "").strip()
                if not worker_name:
                    continue
                workers.append(
                    {
                        "row": index,
                        "name": " ".join(worker_name.split()),
                        "area": (row.get(2) or "").strip(),
                        "nickname": (row.get(3) or "").strip(),
                        "extras": {
                            str(column): value
                            for column, value in row.items()
                            if column not in date_columns and column > 3
                        },
                        "days": [
                            {
                                "date": work_date.isoformat(),
                                "column": column,
                                "value": row.get(column, ""),
                            }
                            for column, work_date in date_columns.items()
                        ],
                    }
                )
            result["sheets"].append(
                {
                    "name": name,
                    "path": sheet_path,
                    "dates": {
                        work_date.isoformat(): column
                        for column, work_date in date_columns.items()
                    },
                    "workers": workers,
                }
            )
    return result


def read_cost_centers(path: str | Path) -> list[dict[str, str]]:
    """Read either the labor Cost Code/Description or legacy ID/Name layout."""
    with ZipFile(path) as archive:
        shared = _shared_strings(archive)
        for _sheet_name, sheet_path in workbook_sheets(archive):
            rows = sheet_rows(archive, sheet_path, shared)
            if not rows:
                continue
            headers = {
                normalize_sheet_name(value).casefold(): column
                for column, value in rows[0].items()
                if normalize_sheet_name(value)
            }
            if "cost code" in headers and "description" in headers:
                id_column, name_column = headers["cost code"], headers["description"]
            elif "id" in headers and "name" in headers:
                id_column, name_column = headers["id"], headers["name"]
            else:
                continue
            centers = []
            seen = set()
            for row in rows[1:]:
                center_id = normalize_sheet_name(row.get(id_column, ""))
                center_name = normalize_sheet_name(row.get(name_column, ""))
                if not center_id or not center_name or center_id in seen:
                    continue
                centers.append({"id": center_id, "name": center_name})
                seen.add(center_id)
            return centers
    return []


def read_worker_information(path: str | Path) -> list[dict]:
    """Read the non-sensitive payroll fields from Worker's Information."""
    with ZipFile(path) as archive:
        shared = _shared_strings(archive)
        for name, sheet_path in workbook_sheets(archive):
            if normalize_sheet_name(name).casefold() != "worker's information":
                continue
            rows = sheet_rows(archive, sheet_path, shared)
            if not rows:
                return []
            headers = {
                normalize_sheet_name(value).casefold(): column
                for column, value in rows[0].items()
            }
            name_column = headers.get("workers name", 1)
            rate_column = headers.get("daily rate", 6)
            schedule_column = headers.get("note info", 4)
            method_column = headers.get("payment method", 9)
            status_column = headers.get("work status", 5)
            output = []
            for row in rows[1:]:
                worker_name = normalize_sheet_name(row.get(name_column, ""))
                if not worker_name:
                    continue
                raw_rate = normalize_sheet_name(row.get(rate_column, ""))
                rate_match = re.search(r"\d+(?:\.\d+)?", raw_rate.replace(",", ""))
                output.append(
                    {
                        "name": worker_name,
                        "daily_rate": float(rate_match.group()) if rate_match else None,
                        "pay_schedule": normalize_sheet_name(row.get(schedule_column, "")),
                        "payment_method": normalize_sheet_name(row.get(method_column, "")),
                        "work_status": normalize_sheet_name(row.get(status_column, "")),
                    }
                )
            return output
    return []


def _set_inline_cell(row: ET.Element, reference: str, value: str) -> None:
    cells = list(row.findall("m:c", NS))
    target = next((cell for cell in cells if cell.attrib.get("r") == reference), None)
    if target is None:
        target = ET.Element(f"{{{MAIN_NS}}}c", {"r": reference})
        target_column = column_number(reference)
        inserted = False
        for index, cell in enumerate(cells):
            if column_number(cell.attrib.get("r", "")) > target_column:
                row.insert(index, target)
                inserted = True
                break
        if not inserted:
            row.append(target)
    for child in list(target):
        target.remove(child)
    target.attrib["t"] = "inlineStr"
    inline = ET.SubElement(target, f"{{{MAIN_NS}}}is")
    text = ET.SubElement(inline, f"{{{MAIN_NS}}}t")
    if value != value.strip():
        text.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
    text.text = value


def _set_number_cell(row: ET.Element, reference: str, value: float) -> None:
    cells = list(row.findall("m:c", NS))
    target = next((cell for cell in cells if cell.attrib.get("r") == reference), None)
    if target is None:
        target = ET.Element(f"{{{MAIN_NS}}}c", {"r": reference})
        target_column = column_number(reference)
        inserted = False
        for index, cell in enumerate(cells):
            if column_number(cell.attrib.get("r", "")) > target_column:
                row.insert(index, target)
                inserted = True
                break
        if not inserted:
            row.append(target)
    for child in list(target):
        target.remove(child)
    target.attrib.pop("t", None)
    numeric = ET.SubElement(target, f"{{{MAIN_NS}}}v")
    numeric.text = f"{float(value):.2f}".rstrip("0").rstrip(".")


def _worksheet_row(sheet_data: ET.Element, row_number: int) -> ET.Element:
    existing = next(
        (
            row for row in sheet_data.findall("m:row", NS)
            if int(row.attrib.get("r", "0")) == row_number
        ),
        None,
    )
    if existing is not None:
        return existing
    row = ET.Element(
        f"{{{MAIN_NS}}}row",
        {"r": str(row_number), "ht": "18", "customHeight": "1"},
    )
    inserted = False
    rows = list(sheet_data.findall("m:row", NS))
    for index, current in enumerate(rows):
        if int(current.attrib.get("r", "0")) > row_number:
            sheet_data.insert(index, row)
            inserted = True
            break
    if not inserted:
        sheet_data.append(row)
    return row


def fill_template_workbook(
    template_path: str | Path,
    output: io.BytesIO,
    *,
    cell_updates: dict[str, dict[str, str | int | float]] | None = None,
    table_rows: dict[str, list[list[str | int | float]]] | None = None,
) -> None:
    """Clone a formatted template and fill fixed cells or append tabular rows."""
    cell_updates = cell_updates or {}
    table_rows = table_rows or {}
    with ZipFile(template_path) as source:
        replacements: dict[str, bytes] = {}
        for sheet_name, sheet_path in workbook_sheets(source):
            updates = cell_updates.get(sheet_name, {})
            rows_to_append = table_rows.get(sheet_name)
            if not updates and rows_to_append is None:
                continue
            root = ET.fromstring(source.read(sheet_path))
            sheet_data = root.find("m:sheetData", NS)
            if sheet_data is None:
                continue
            for reference, value in updates.items():
                match = re.fullmatch(r"([A-Z]+)(\d+)", reference.upper())
                if not match:
                    raise ValueError(f"Invalid spreadsheet cell reference: {reference}")
                row = _worksheet_row(sheet_data, int(match.group(2)))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    _set_number_cell(row, reference.upper(), float(value))
                else:
                    _set_inline_cell(row, reference.upper(), str(value))
            if rows_to_append is not None:
                for old_row in list(sheet_data.findall("m:row", NS)):
                    if int(old_row.attrib.get("r", "0")) > 1:
                        sheet_data.remove(old_row)
                for row_number, values in enumerate(rows_to_append, start=2):
                    row = _worksheet_row(sheet_data, row_number)
                    for column, value in enumerate(values, start=1):
                        reference = f"{column_letters(column)}{row_number}"
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            _set_number_cell(row, reference, float(value))
                        else:
                            _set_inline_cell(row, reference, str(value))
                last_row = max(1, len(rows_to_append) + 1)
                dimension = root.find("m:dimension", NS)
                if dimension is not None:
                    dimension.attrib["ref"] = f"A1:I{last_row}"
                for old_filter in root.findall("m:autoFilter", NS):
                    root.remove(old_filter)
                auto_filter = ET.Element(
                    f"{{{MAIN_NS}}}autoFilter",
                    {"ref": f"A1:I{last_row}"},
                )
                root.insert(list(root).index(sheet_data) + 1, auto_filter)
            root.attrib.pop(f"{{{MC_NS}}}Ignorable", None)
            root.attrib.pop(f"{{{XR_NS}}}uid", None)
            replacements[sheet_path] = ET.tostring(
                root, encoding="utf-8", xml_declaration=True
            )
        with ZipFile(output, "w", ZIP_DEFLATED) as destination:
            for item in source.infolist():
                destination.writestr(
                    item, replacements.get(item.filename, source.read(item.filename))
                )


def update_workbook(
    template_path: str | Path,
    output: io.BytesIO,
    updates: Iterable[dict],
    year: int,
) -> None:
    """Clone a workbook and update matching worker/date work cells."""
    updates_by_key = {
        (
            item["worker_name"].strip().casefold(),
            int(item.get("occurrence", 1)),
            item["date"],
        ): item["value"]
        for item in updates
    }
    with ZipFile(template_path) as source:
        shared = _shared_strings(source)
        sheets = workbook_sheets(source)
        replacements: dict[str, bytes] = {}
        for sheet_name, sheet_path in sheets:
            root = ET.fromstring(source.read(sheet_path))
            rows = root.findall("m:sheetData/m:row", NS)
            if not rows:
                continue
            date_columns = {}
            for cell in rows[0].findall("m:c", NS):
                work_date = parse_header_date(cell_value(cell, shared), year)
                if work_date:
                    date_columns[work_date.isoformat()] = column_number(
                        cell.attrib.get("r", "")
                    )
            if not date_columns:
                continue
            changed = False
            name_occurrences: dict[str, int] = {}
            for row in rows[1:]:
                name_cell = next(
                    (
                        cell
                        for cell in row.findall("m:c", NS)
                        if column_number(cell.attrib.get("r", "")) == 1
                    ),
                    None,
                )
                if name_cell is None:
                    continue
                worker_name = " ".join(cell_value(name_cell, shared).split())
                name_key = worker_name.casefold()
                name_occurrences[name_key] = name_occurrences.get(name_key, 0) + 1
                occurrence = name_occurrences[name_key]
                row_number = int(row.attrib.get("r", "0"))
                for iso_date, column in date_columns.items():
                    key = (name_key, occurrence, iso_date)
                    if key in updates_by_key:
                        _set_inline_cell(
                            row,
                            f"{column_letters(column)}{row_number}",
                            updates_by_key[key],
                        )
                        changed = True
            if changed:
                # ElementTree does not retain unused namespace declarations.
                # The source workbook's mc:Ignorable value references dozens
                # of prefixes that then disappear, which makes Excel report a
                # damaged worksheet. These revision metadata attributes are
                # optional, so remove them from rewritten sheets.
                root.attrib.pop(f"{{{MC_NS}}}Ignorable", None)
                root.attrib.pop(f"{{{XR_NS}}}uid", None)
                replacements[sheet_path] = ET.tostring(
                    root, encoding="utf-8", xml_declaration=True
                )

        with ZipFile(output, "w", ZIP_DEFLATED) as destination:
            for item in source.infolist():
                destination.writestr(
                    item, replacements.get(item.filename, source.read(item.filename))
                )


def half_month_name(day: date) -> str:
    month = calendar.month_name[day.month]
    if day.day <= 15:
        return f"{month} 1-15"
    return f"{month} 16-{calendar.monthrange(day.year, day.month)[1]}"
