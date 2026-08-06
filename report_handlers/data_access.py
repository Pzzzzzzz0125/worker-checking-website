from __future__ import annotations

import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._shared import (
    cookie_header,
    cookie_value,
    json_response,
    secure_cookie,
    sign_payload,
    verify_payload,
)
from report_handlers.workers import admin_ids, session
from api._permissions import is_super_admin


def action(handler: BaseHTTPRequestHandler) -> str:
    return parse_qs(urlparse(handler.path).query).get("action", [""])[0]


def import_access_status(current_session: dict) -> dict:
    authorized = is_super_admin(current_session)
    return {
        "authorized": authorized,
        "access_type": "lark_admin" if authorized else "",
        "admin_allowlist_configured": bool(admin_ids()),
    }


def export_access_status(
    handler: BaseHTTPRequestHandler,
    current_session: dict,
) -> dict:
    password_session = verify_payload(
        cookie_value(handler, "export_access_session"),
        8 * 60 * 60,
    )
    authorized = bool(
        password_session
        and password_session.get("scope") == "exports"
        and password_session.get("sub") == current_session.get("sub")
    )
    return {
        "authorized": authorized,
        "access_type": "password" if authorized else "",
        "password_configured": bool(os.environ.get("EXPORT_PASSWORD", "").strip()),
    }


def require_export_access(handler: BaseHTTPRequestHandler) -> bool:
    current = session(handler)
    if not current:
        json_response(handler, {"error": "Sign in with Lark first."}, 401)
        return False
    access = export_access_status(handler, current)
    if access["authorized"]:
        return True
    json_response(
        handler,
        {
            "error": "Export requires the Export password.",
            "code": "export_access_required",
            **access,
        },
        403,
    )
    return False


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        current = session(self)
        if not current:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        selected = action(self)
        if selected == "import_access":
            json_response(self, import_access_status(current))
            return
        if selected == "export_access":
            json_response(self, export_access_status(self, current))
            return
        json_response(self, {"error": "Unknown data-access route."}, 404)

    def do_POST(self) -> None:
        current = session(self)
        if not current:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        if action(self) != "export_unlock":
            json_response(self, {"error": "Unknown data-access route."}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Invalid export access request: {error}"}, 400)
            return

        configured = os.environ.get("EXPORT_PASSWORD", "").strip()
        supplied = str(body.get("password") or "")
        if not configured:
            json_response(
                self,
                {
                    "error": "EXPORT_PASSWORD is not configured in Vercel.",
                    "code": "export_password_not_configured",
                },
                503,
            )
            return
        if not hmac.compare_digest(supplied, configured):
            json_response(self, {"error": "Incorrect Export password."}, 403)
            return
        grant = sign_payload(
            {
                "sub": current.get("sub", ""),
                "scope": "exports",
                "iat": int(time.time()),
            }
        )
        json_response(
            self,
            {"authorized": True, "access_type": "password"},
            headers={
                "Set-Cookie": cookie_header(
                    "export_access_session",
                    grant,
                    8 * 60 * 60,
                    secure_cookie(self),
                )
            },
        )
