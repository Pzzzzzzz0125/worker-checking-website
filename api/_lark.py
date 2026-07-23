from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LARK_API = "https://open.larksuite.com/open-apis"
_TENANT_TOKEN = ""
_TENANT_TOKEN_EXPIRES_AT = 0.0


class LarkAPIError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


def _read_json(request: Request) -> dict:
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8"))
            message = detail.get("msg") or detail.get("message") or str(error)
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = str(error)
        raise LarkAPIError(message, status=error.code) from error
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LarkAPIError(f"Could not reach Lark: {error}") from error
    if not isinstance(payload, dict):
        raise LarkAPIError("Lark returned an invalid response.")
    code = payload.get("code", 0)
    if code not in (0, None):
        message = payload.get("msg") or payload.get("message") or "Lark API request failed."
        status = 403 if code in {99991663, 99991672, 1254302} else 502
        raise LarkAPIError(f"{message} (Lark code {code})", code=code, status=status)
    return payload


def tenant_access_token() -> str:
    global _TENANT_TOKEN, _TENANT_TOKEN_EXPIRES_AT
    if _TENANT_TOKEN and time.monotonic() < _TENANT_TOKEN_EXPIRES_AT:
        return _TENANT_TOKEN
    app_id = os.environ.get("LARK_APP_ID", "").strip()
    app_secret = os.environ.get("LARK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise LarkAPIError("LARK_APP_ID and LARK_APP_SECRET are not configured.", status=503)
    request = Request(
        f"{LARK_API}/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    payload = _read_json(request)
    token = payload.get("tenant_access_token", "")
    if not token:
        raise LarkAPIError("Lark did not return a tenant access token.")
    # Lark tokens normally last two hours. Refresh one minute early and retain
    # the token inside a warm Vercel function instead of requesting one on
    # every browser refresh.
    lifetime = max(int(payload.get("expire") or 7200) - 60, 60)
    _TENANT_TOKEN = str(token)
    _TENANT_TOKEN_EXPIRES_AT = time.monotonic() + lifetime
    return token


def lark_api(
    method: str,
    path: str,
    *,
    token: str,
    body: dict | None = None,
    query: dict[str, str | int] | None = None,
) -> dict:
    url = f"{LARK_API}{path}"
    if query:
        url += "?" + urlencode(query)
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method=method,
    )
    return _read_json(request)


def lark_download(path: str, *, token: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
    """Download a binary Lark resource with a conservative serverless size cap."""
    request = Request(
        f"{LARK_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length", "")
            if content_length and int(content_length) > max_bytes:
                raise LarkAPIError(
                    f"Lark file exceeds the {max_bytes // (1024 * 1024)} MB preview limit.",
                    status=413,
                )
            content = response.read(max_bytes + 1)
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8"))
            message = detail.get("msg") or detail.get("message") or str(error)
            code = detail.get("code")
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = str(error)
            code = None
        status = 403 if error.code == 403 else error.code
        raise LarkAPIError(message, code=code, status=status) from error
    except (URLError, TimeoutError, ValueError) as error:
        raise LarkAPIError(f"Could not download the Lark file: {error}") from error
    if len(content) > max_bytes:
        raise LarkAPIError(
            f"Lark file exceeds the {max_bytes // (1024 * 1024)} MB preview limit.",
            status=413,
        )
    return content


def paged_items(path: str, *, token: str, page_size: int = 100) -> list[dict]:
    items: list[dict] = []
    page_token = ""
    while True:
        query: dict[str, str | int] = {"page_size": page_size}
        if page_token:
            query["page_token"] = page_token
        payload = lark_api("GET", path, token=token, query=query)
        data = payload.get("data") or {}
        page_items = data.get("items") or []
        if not isinstance(page_items, list):
            raise LarkAPIError("Lark returned an invalid paginated response.")
        items.extend(item for item in page_items if isinstance(item, dict))
        if not data.get("has_more"):
            return items
        page_token = str(data.get("page_token") or "")
        if not page_token:
            raise LarkAPIError("Lark pagination did not return a page token.")
