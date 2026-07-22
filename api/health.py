from http.server import BaseHTTPRequestHandler

from api._shared import json_response


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        json_response(self, {"ok": True, "service": "speed-construction-workforce"})
