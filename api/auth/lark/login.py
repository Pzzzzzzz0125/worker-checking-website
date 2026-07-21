from __future__ import annotations

import os
import secrets
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode

from api._shared import (
    callback_url,
    cookie_header,
    json_response,
    redirect,
    secure_cookie,
    sign_payload,
)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        app_id = os.environ.get("LARK_APP_ID", "").strip()
        if not app_id:
            json_response(self, {"error": "LARK_APP_ID is not configured."}, 503)
            return
        try:
            state = sign_payload({"nonce": secrets.token_urlsafe(24), "iat": int(time.time())})
        except ValueError as error:
            json_response(self, {"error": str(error)}, 503)
            return
        scopes = os.environ.get("LARK_OAUTH_SCOPES", "offline_access").strip()
        query = {
            "client_id": app_id,
            "redirect_uri": callback_url(self),
            "state": state,
        }
        if scopes:
            query["scope"] = scopes
        authorize = "https://accounts.larksuite.com/open-apis/authen/v1/authorize?" + urlencode(query)
        redirect(
            self,
            authorize,
            [cookie_header("lark_oauth_state", state, 10 * 60, secure_cookie(self))],
        )
