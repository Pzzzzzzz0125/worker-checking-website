from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler

from api._shared import json_response


MAX_BODY_BYTES = 1_000_000
BASE_RECORD_CHANGED = "drive.file.bitable_record_changed_v1"


def _verification_token(payload: dict) -> str:
    header = payload.get("header")
    if isinstance(header, dict):
        token = header.get("token")
        if isinstance(token, str):
            return token
    token = payload.get("token")
    return token if isinstance(token, str) else ""


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        json_response(
            self,
            {
                "ok": True,
                "service": "lark-events",
                "message": "Send Lark event callbacks to this endpoint with POST.",
            },
        )

    def do_POST(self) -> None:
        expected_token = os.environ.get("LARK_VERIFICATION_TOKEN", "").strip()
        if not expected_token:
            json_response(
                self,
                {"error": "LARK_VERIFICATION_TOKEN is not configured."},
                503,
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            json_response(self, {"error": "Invalid Content-Length header."}, 400)
            return
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            json_response(self, {"error": "Invalid event request size."}, 400)
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            json_response(self, {"error": "Request body must be valid JSON."}, 400)
            return
        if not isinstance(payload, dict):
            json_response(self, {"error": "Event payload must be a JSON object."}, 400)
            return
        if "encrypt" in payload:
            json_response(
                self,
                {"error": "Encrypted Lark events are not enabled. Leave Encrypt Key empty in Lark."},
                400,
            )
            return

        supplied_token = _verification_token(payload)
        if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
            json_response(self, {"error": "Invalid Lark verification token."}, 401)
            return

        challenge = payload.get("challenge")
        if isinstance(challenge, str) and challenge:
            json_response(self, {"challenge": challenge})
            return

        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        event_type = header.get("event_type") or payload.get("type", "")
        event_id = header.get("event_id", "")

        # Lark Base remains the source of truth. The callback is acknowledged
        # immediately; consumers can re-read the affected Base records afterward.
        json_response(
            self,
            {
                "code": 0,
                "received": True,
                "event_id": event_id,
                "supported": event_type == BASE_RECORD_CHANGED,
            },
        )
