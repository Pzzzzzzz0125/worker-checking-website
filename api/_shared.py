from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from http.cookies import SimpleCookie
from urllib.parse import urlparse


def json_response(
    handler, body: dict, status: int = 200, headers: dict[str, str] | None = None,
) -> None:
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Data-Backend", os.environ.get("DATA_BACKEND", "lark"))
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def redirect(handler, location: str, cookies: list[str] | None = None) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    for value in cookies or []:
        handler.send_header("Set-Cookie", value)
    handler.end_headers()


def app_url(handler) -> str:
    configured = os.environ.get("APP_URL", "").strip().rstrip("/")
    if configured:
        return configured
    production = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "").strip().rstrip("/")
    if production:
        return production if production.startswith("http") else f"https://{production}"
    forwarded = handler.headers.get("x-forwarded-host") or handler.headers.get("host", "localhost:8000")
    scheme = handler.headers.get("x-forwarded-proto") or ("http" if forwarded.startswith("localhost") else "https")
    return f"{scheme}://{forwarded}"


def callback_url(handler) -> str:
    return f"{app_url(handler)}/api/auth/lark/callback"


def cookie_value(handler, name: str) -> str:
    cookie = SimpleCookie()
    cookie.load(handler.headers.get("cookie", ""))
    return cookie[name].value if name in cookie else ""


def cookie_header(name: str, value: str, max_age: int, secure: bool = True) -> str:
    parts = [f"{name}={value}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _secret() -> bytes:
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise ValueError("SESSION_SECRET must contain at least 32 characters.")
    return secret.encode("utf-8")


def sign_payload(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def verify_payload(value: str, max_age: int) -> dict | None:
    try:
        encoded, supplied = value.rsplit(".", 1)
        expected = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            return None
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw)
        issued = int(payload.get("iat", 0))
        if issued <= 0 or time.time() - issued > max_age:
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error):
        return None


def secure_cookie(handler) -> bool:
    return urlparse(app_url(handler)).scheme == "https"
