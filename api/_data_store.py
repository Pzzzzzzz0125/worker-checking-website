from __future__ import annotations

import os

from api._lark import LarkAPIError
from api._lark_base import LarkBase
from api._postgres_base import PostgresBase


def DataStore():
    backend = os.environ.get("DATA_BACKEND", "lark").strip().casefold()
    if backend == "postgres":
        return PostgresBase()
    if backend == "lark":
        return LarkBase()
    raise LarkAPIError("DATA_BACKEND must be 'postgres' or 'lark'.", status=503)
