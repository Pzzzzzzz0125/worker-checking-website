from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from api._lark import LarkAPIError
from api._permissions import (
    access_snapshot,
    review_request,
    set_user_role,
    submit_request,
)
from api._shared import cookie_value, json_response, verify_payload


def current_session(handler: BaseHTTPRequestHandler) -> dict | None:
    return verify_payload(
        cookie_value(handler, "workforce_session"), 12 * 60 * 60,
    )


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        session = current_session(self)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            json_response(self, access_snapshot(session))
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)

    def do_POST(self) -> None:
        session = current_session(self)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("The request body must be an object.")
            action = str(body.get("action") or "")
            if action == "request":
                submit_request(
                    session,
                    str(body.get("requested_role") or ""),
                    str(body.get("reason") or ""),
                )
            elif action == "review":
                review_request(
                    session,
                    int(body.get("request_id") or 0),
                    str(body.get("decision") or ""),
                    str(body.get("review_note") or ""),
                )
            elif action == "set_role":
                set_user_role(
                    session,
                    str(body.get("open_id") or ""),
                    str(body.get("role") or ""),
                )
            else:
                raise ValueError("Choose a valid access-settings action.")
            json_response(self, access_snapshot(session))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            json_response(self, {"error": str(error)}, 400)
        except PermissionError as error:
            json_response(self, {"error": str(error)}, 403)
        except LarkAPIError as error:
            json_response(self, {"error": str(error)}, error.status)
