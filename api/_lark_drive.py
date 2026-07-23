from __future__ import annotations

import os
import re
import time
import unicodedata
from urllib.parse import quote

from api._lark import LarkAPIError, lark_api, lark_download


def drive_folder_token() -> str:
    token = os.environ.get("LARK_DRIVE_FOLDER_TOKEN", "").strip()
    if not token:
        raise LarkAPIError("LARK_DRIVE_FOLDER_TOKEN is not configured.", status=503)
    return token


def folder_files(token: str, folder_token: str) -> list[dict]:
    files: list[dict] = []
    page_token = ""
    while True:
        query: dict[str, str | int] = {
            "folder_token": folder_token,
            "page_size": 200,
        }
        if page_token:
            query["page_token"] = page_token
        payload = lark_api("GET", "/drive/v1/files", token=token, query=query)
        data = payload.get("data") or {}
        items = data.get("files") or data.get("items") or []
        if not isinstance(items, list):
            raise LarkAPIError("Lark returned an invalid Drive folder response.")
        files.extend(item for item in items if isinstance(item, dict))
        if not data.get("has_more"):
            return files
        page_token = str(data.get("next_page_token") or data.get("page_token") or "")
        if not page_token:
            raise LarkAPIError("Lark Drive pagination did not return a page token.")


def file_name(item: dict) -> str:
    return str(item.get("name") or item.get("title") or "").strip()


def file_token(item: dict) -> str:
    return str(item.get("token") or item.get("file_token") or "").strip()


def normalized_file_name(value: str) -> str:
    """Match harmless Lark filename changes without accepting a different title."""
    value = value.translate(str.maketrans({"’": "'", "‘": "'", "‛": "'"}))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", value.casefold())
    if words[-1:] == ["xlsx"]:
        words.pop()
    return " ".join(words)


def exact_file(files: list[dict], name: str) -> dict:
    expected = normalized_file_name(name)
    matches = [item for item in files if normalized_file_name(file_name(item)) == expected]
    if not matches:
        available = [file_name(item) for item in files if file_name(item)][:10]
        detail = f" Available files: {', '.join(available)}." if available else " The folder appears empty."
        raise LarkAPIError(f'Lark Drive folder is missing "{name}".{detail}', status=404)
    if len(matches) > 1:
        raise LarkAPIError(
            f'Lark Drive folder contains more than one file named "{name}". Keep only the current copy.',
            status=409,
        )
    if not file_token(matches[0]):
        raise LarkAPIError(f'Lark did not return a token for "{name}".')
    return matches[0]


def download_file(item: dict, token: str) -> bytes:
    source_token = file_token(item)
    source_type = str(item.get("type") or "file").casefold()
    encoded = quote(source_token, safe="")
    if source_type == "sheet":
        return _export_sheet(source_token, token)
    try:
        # Files listed directly in a Drive folder use the Drive file-download
        # route. The media route is for attachments embedded in cloud docs.
        return lark_download(f"/drive/v1/files/{encoded}/download", token=token)
    except LarkAPIError as error:
        if error.status != 404:
            raise
        # Retain compatibility with older uploaded assets returned as `file`.
        return lark_download(f"/drive/v1/medias/{encoded}/download", token=token)


def _export_sheet(source_token: str, token: str) -> bytes:
    created = lark_api(
        "POST",
        "/drive/v1/export_tasks",
        token=token,
        body={"file_extension": "xlsx", "token": source_token, "type": "sheet"},
    )
    ticket = str((created.get("data") or {}).get("ticket") or "")
    if not ticket:
        raise LarkAPIError("Lark did not return a ticket for the spreadsheet export.")
    for _ in range(30):
        result_payload = lark_api(
            "GET",
            f"/drive/v1/export_tasks/{quote(ticket, safe='')}",
            token=token,
            query={"token": source_token},
        )
        result = (result_payload.get("data") or {}).get("result") or {}
        exported_token = str(result.get("file_token") or "")
        if exported_token:
            return lark_download(
                f"/drive/v1/export_tasks/file/{quote(exported_token, safe='')}/download",
                token=token,
            )
        error_message = str(result.get("job_error_msg") or "")
        if result.get("job_status") == 0 and error_message.casefold() not in {"", "success"}:
            raise LarkAPIError(f"Lark spreadsheet export failed: {error_message}")
        time.sleep(0.6)
    raise LarkAPIError("Lark spreadsheet export timed out. Try the preview again.", status=504)
