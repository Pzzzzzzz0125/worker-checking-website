from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from api._shared import sign_payload
from report_handlers.data_access import export_access_status, import_access_status


class FakeHandler:
    def __init__(self, cookie: str = "") -> None:
        self.headers = {"cookie": cookie} if cookie else {}


class DataAccessTests(unittest.TestCase):
    def test_import_requires_allowlisted_lark_admin(self) -> None:
        with patch.dict(os.environ, {"LARK_ADMIN_OPEN_IDS": "ou_admin"}, clear=False):
            self.assertTrue(import_access_status({"sub": "ou_admin"})["authorized"])
            self.assertFalse(import_access_status({"sub": "ou_worker"})["authorized"])

    def test_export_requires_separate_password_grant(self) -> None:
        environment = {
            "SESSION_SECRET": "test-session-secret-that-is-long-enough",
            "EXPORT_PASSWORD": "separate-export-password",
        }
        with patch.dict(os.environ, environment, clear=False):
            current = {"sub": "ou_admin"}
            self.assertFalse(export_access_status(FakeHandler(), current)["authorized"])
            token = sign_payload(
                {
                    "sub": current["sub"],
                    "scope": "exports",
                    "iat": int(time.time()),
                }
            )
            status = export_access_status(
                FakeHandler(f"export_access_session={token}"),
                current,
            )
            self.assertTrue(status["authorized"])
            self.assertEqual(status["access_type"], "password")

    def test_export_grant_is_bound_to_signed_in_user(self) -> None:
        environment = {
            "SESSION_SECRET": "test-session-secret-that-is-long-enough",
            "EXPORT_PASSWORD": "separate-export-password",
        }
        with patch.dict(os.environ, environment, clear=False):
            token = sign_payload(
                {
                    "sub": "ou_first",
                    "scope": "exports",
                    "iat": int(time.time()),
                }
            )
            status = export_access_status(
                FakeHandler(f"export_access_session={token}"),
                {"sub": "ou_second"},
            )
            self.assertFalse(status["authorized"])


if __name__ == "__main__":
    unittest.main()
