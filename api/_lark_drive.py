from __future__ import annotations

import os
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


def exact_file(files: list[dict], name: str) -> dict:
    matches = [item for item in files if file_name(item) == name]
    if not matches:
        raise LarkAPIError(f'Lark Drive folder is missing "{name}".', status=404)
    if len(matches) > 1:
        raise LarkAPIError(
            f'Lark Drive folder contains more than one file named "{name}". Keep only the current copy.',
            status=409,
        )
    if not file_token(matches[0]):
        raise LarkAPIError(f'Lark did not return a token for "{name}".')
    return matches[0]


def download_file(item: dict, token: str) -> bytes:
    return lark_download(
        f"/drive/v1/medias/{quote(file_token(item), safe='')}/download",
        token=token,
    )
