from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from api._lark import LarkAPIError
from api._data_store import DataStore
from api._lark_base import LarkBase
from api._shared import cookie_value, json_response, verify_payload
from api.bootstrap import build_bootstrap_details


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        session = verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60)
        if not session:
            json_response(self, {"error": "Sign in with Lark first."}, 401)
            return
        try:
            json_response(self, build_bootstrap_details(DataStore()))
        except LarkAPIError as error:
            json_response(self, {"error": str(error), "lark_code": error.code}, error.status)
