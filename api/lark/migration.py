from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from api._lark import LarkAPIError, tenant_access_token
from api._lark_drive import (
    download_file,
    drive_folder_token,
    exact_file,
    file_name,
    folder_files,
)
from api._migration_preview import build_preview
from api._shared import cookie_value, json_response, verify_payload


FILES = (
    "2026 Worker's information - location standardized.xlsx",
    "Cost Code and Cost Type Keep the Most Updated.xlsx",
    "Speed Payroll.xlsx",
)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        session = verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        admins = {
            value.strip()
            for value in os.environ.get("LARK_ADMIN_OPEN_IDS", "").split(",")
            if value.strip()
        }
        if not admins or session.get("sub") not in admins:
            json_response(self, {"error": "Only a configured Lark administrator can preview migration."}, 403)
            return
        try:
            token = tenant_access_token()
            files = folder_files(token, drive_folder_token())
            selected = [exact_file(files, name) for name in FILES]
            with ThreadPoolExecutor(max_workers=3) as executor:
                contents = list(executor.map(lambda item: download_file(item, token), selected))
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
