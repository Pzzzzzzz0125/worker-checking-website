from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

from api._lark import LarkAPIError, tenant_access_token
from api._lark_base import LarkBase
from api._lark_drive import (
    download_file,
    drive_folder_token,
    exact_file,
    file_name,
    folder_files,
)
from api._migration_preview import build_dataset, build_preview
from api._shared import cookie_value, json_response, verify_payload


FILES = (
    "2026 Worker's information - location standardized.xlsx",
    "Cost Code and Cost Type Keep the Most Updated.xlsx",
    "Speed Payroll.xlsx",
)
CONFIRMATION = "IMPORT VERIFIED PREVIEW"


def _admin_session(handler: BaseHTTPRequestHandler) -> dict | None:
    session = verify_payload(cookie_value(handler, "workforce_session"), 12 * 60 * 60)
    if not session:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return None
    admins = {
        value.strip()
        for value in os.environ.get("LARK_ADMIN_OPEN_IDS", "").split(",")
        if value.strip()
    }
    if not admins or session.get("sub") not in admins:
        json_response(handler, {"error": "Only a configured Lark administrator can run migration."}, 403)
        return None
    return session


def _drive_contents(token: str) -> tuple[list[dict], list[bytes]]:
    files = folder_files(token, drive_folder_token())
    selected = [exact_file(files, name) for name in FILES]
    with ThreadPoolExecutor(max_workers=3) as executor:
        contents = list(executor.map(lambda item: download_file(item, token), selected))
    return selected, contents


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not _admin_session(self):
            return
        try:
            token = tenant_access_token()
            selected, contents = _drive_contents(token)
            preview = build_preview(*contents, year=2026)
            preview["files"] = [
                {
                    "name": file_name(item),
                    "type": item.get("type", ""),
                    "modified_time": item.get("modified_time", ""),
                }
                for item in selected
            ]
            json_response(self, preview)
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
        except (BadZipFile, ParseError, KeyError, ValueError, OSError) as error:
            json_response(self, {"error": f"Could not parse the uploaded workbooks: {error}"}, 422)

    def do_POST(self) -> None:
        session = _admin_session(self)
        if not session:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            json_response(self, {"error": "Request body must be valid JSON."}, 400)
            return
        if body.get("confirm") != CONFIRMATION:
            json_response(
                self,
                {"error": f'To import, confirmation must equal "{CONFIRMATION}".'},
                400,
            )
            return
        try:
            token = tenant_access_token()
            _selected, contents = _drive_contents(token)
            dataset = build_dataset(*contents, year=2026)
            preview = dataset["preview"]
            if not preview["safe_to_write"]:
                raise LarkAPIError("Migration preview checks did not pass.", status=409)
            base = LarkBase()
            missing_tables = base.missing_tables()
            if missing_tables:
                raise LarkAPIError(
                    "Lark Base setup is incomplete. Missing: " + ", ".join(missing_tables),
                    status=503,
                )
            results = {}
            for table_name, key_field in (
                ("Workers", "Worker Key"),
                ("Cost Centers", "Cost Center ID"),
                ("Work Days", "Work Day Key"),
                ("Location Entries", "Location Entry Key"),
            ):
                results[table_name] = base.create_missing(
                    table_name,
                    key_field,
                    dataset["tables"][table_name],
                )
            now = int(datetime.now(tz=ZoneInfo("America/Los_Angeles")).timestamp() * 1000)
            results["Audit Log"] = base.create_missing(
                "Audit Log",
                "Audit Key",
                [
                    {
                        "Audit Key": "migration|2026-standardized-v1",
                        "Actor ID": session.get("sub", ""),
                        "Actor Name": session.get("name", ""),
                        "Action": "verified-workbook-migration",
                        "Entity Type": "Lark Base",
                        "Entity Key": "2026-standardized-v1",
                        "Old JSON": "",
                        "New JSON": json.dumps(preview["counts"], separators=(",", ":")),
                        "Source": "lark-drive-migration",
                        "Created At": now,
                    }
                ],
            )
            json_response(
                self,
                {
                    "mode": "import_complete",
                    "retry_safe": True,
                    "results": results,
                    "preview": {
                        "counts": preview["counts"],
                        "totals": preview["totals"],
                        "date_range": preview["date_range"],
                    },
                },
            )
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
        except (BadZipFile, ParseError, KeyError, ValueError, OSError) as error:
            json_response(self, {"error": f"Could not import the uploaded workbooks: {error}"}, 422)
