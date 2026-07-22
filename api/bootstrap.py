import os
from http.server import BaseHTTPRequestHandler

from api._shared import json_response


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        json_response(
            self,
            {
                "error": "Lark Base setup is not connected yet.",
                "code": "setup_required",
                "setup_required": True,
                "login_enabled": bool(os.environ.get("LARK_APP_ID")),
            },
            503,
        )
