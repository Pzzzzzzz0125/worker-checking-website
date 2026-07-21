from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from api._shared import (
    callback_url,
    cookie_header,
    cookie_value,
    json_response,
    redirect,
    secure_cookie,
    sign_payload,
    verify_payload,
)


def request_json(request: Request) -> dict:
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        if query.get("error"):
            json_response(self, {"error": f"Lark authorization was denied: {query['error'][0]}"}, 400)
            return
        code = query.get("code", [""])[0]
        state = query.get("state", [""])[0]
        saved_state = cookie_value(self, "lark_oauth_state")
        if not code or state != saved_state or not verify_payload(state, 10 * 60):
            json_response(self, {"error": "Invalid or expired Lark OAuth response."}, 400)
            return
        app_id = os.environ.get("LARK_APP_ID", "").strip()
        app_secret = os.environ.get("LARK_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            json_response(self, {"error": "Lark OAuth credentials are not configured."}, 503)
            return
        token_request = Request(
            "https://open.larksuite.com/open-apis/authen/v2/oauth/token",
            data=json.dumps(
                {
                    "grant_type": "authorization_code",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "code": code,
                    "redirect_uri": callback_url(self),
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            token = request_json(token_request)
            access_token = token.get("access_token", "")
            if not access_token:
                raise ValueError(token.get("error_description") or token.get("message") or "Lark did not return an access token.")
            user_request = Request(
                "https://open.larksuite.com/open-apis/authen/v1/user_info",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user = request_json(user_request).get("data", {})
            user_id = user.get("open_id") or user.get("union_id") or user.get("user_id")
            if not user_id:
                raise ValueError("Lark did not return a user identity.")
            session = sign_payload(
                {
                    "sub": user_id,
                    "name": user.get("name", ""),
                    "avatar": user.get("avatar_url", ""),
                    "iat": int(time.time()),
                }
            )
        except (HTTPError, URLError, ValueError, json.JSONDecodeError) as error:
            json_response(self, {"error": f"Lark login failed: {error}"}, 502)
            return
        redirect(
            self,
            "/",
            [
                cookie_header("workforce_session", session, 12 * 60 * 60, secure_cookie(self)),
                cookie_header("lark_oauth_state", "", 0, secure_cookie(self)),
            ],
        )
