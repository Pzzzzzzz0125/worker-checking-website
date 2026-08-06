import os
import unittest
from unittest.mock import patch

from api._permissions import (
    REQUESTABLE_ROLES,
    is_super_admin,
    permissions_for,
    role_allows,
)


class PermissionTests(unittest.TestCase):
    def test_role_hierarchy(self):
        self.assertTrue(role_allows("super_admin", "schedule_manager"))
        self.assertTrue(role_allows("schedule_manager", "entry_user"))
        self.assertTrue(role_allows("entry_user", "viewer"))
        self.assertFalse(role_allows("viewer", "entry_user"))

    def test_entry_and_conflict_permissions_are_separate(self):
        entry = permissions_for("entry_user")
        manager = permissions_for("schedule_manager")
        self.assertTrue(entry["can_enter"])
        self.assertFalse(entry["can_approve_conflicts"])
        self.assertTrue(manager["can_approve_conflicts"])
        self.assertFalse(manager["can_manage_access"])

    def test_super_admin_cannot_be_self_requested(self):
        self.assertNotIn("super_admin", REQUESTABLE_ROLES)

    def test_vercel_allowlist_is_bootstrap_super_admin(self):
        with patch.dict(os.environ, {"LARK_ADMIN_OPEN_IDS": "ou-owner"}):
            self.assertTrue(is_super_admin({"sub": "ou-owner"}))


if __name__ == "__main__":
    unittest.main()
