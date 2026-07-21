from http.server import BaseHTTPRequestHandler

from api._shared import cookie_value, json_response, verify_payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        session = verify_payload(cookie_value(self, "workforce_session"), 12 * 60 * 60)
        if not session:
            json_response(self, {"authenticated": False}, 401)
            return
        json_response(
            self,
            {
                "authenticated": True,
                "user": {
                    "id": session.get("sub", ""),
                    "name": session.get("name", ""),
                    "avatar": session.get("avatar", ""),
                },
            },
        )
