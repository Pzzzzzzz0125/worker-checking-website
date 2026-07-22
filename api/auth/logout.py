from http.server import BaseHTTPRequestHandler

from api._shared import cookie_header, redirect, secure_cookie


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        redirect(
            self,
            "/",
            [cookie_header("workforce_session", "", 0, secure_cookie(self))],
        )
