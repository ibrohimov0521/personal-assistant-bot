import os
import tempfile
import unittest
from pathlib import Path

import access_control


class AccessControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_allowed_file = access_control.ALLOWED_USERS_FILE
        self.old_blocked_file = access_control.BLOCKED_USERS_FILE
        self.old_allowed_env = os.environ.get("ALLOWED_USER_IDS")
        self.old_admin_env = os.environ.get("ADMIN_USER_IDS")
        access_control.ALLOWED_USERS_FILE = Path(self.tempdir.name) / "allowed.txt"
        access_control.BLOCKED_USERS_FILE = Path(self.tempdir.name) / "blocked.txt"
        os.environ["ALLOWED_USER_IDS"] = ""
        os.environ["ADMIN_USER_IDS"] = "100"

    def tearDown(self) -> None:
        access_control.ALLOWED_USERS_FILE = self.old_allowed_file
        access_control.BLOCKED_USERS_FILE = self.old_blocked_file
        if self.old_allowed_env is None:
            os.environ.pop("ALLOWED_USER_IDS", None)
        else:
            os.environ["ALLOWED_USER_IDS"] = self.old_allowed_env
        if self.old_admin_env is None:
            os.environ.pop("ADMIN_USER_IDS", None)
        else:
            os.environ["ADMIN_USER_IDS"] = self.old_admin_env
        self.tempdir.cleanup()

    def test_parse_user_id_set_ignores_invalid_values(self) -> None:
        self.assertEqual(access_control.parse_user_id_set("1, 2; abc\n3"), {1, 2, 3})

    def test_grant_blocked_user_unblocks_and_allows(self) -> None:
        access_control.BLOCKED_USERS_FILE.write_text("200\n", encoding="utf-8")
        action, message = access_control.grant_user_access(200)
        self.assertEqual(action, "allow_user")
        self.assertIn("blokdan chiqarildi", message)
        self.assertIn(200, access_control.allowed_user_ids())
        self.assertNotIn(200, access_control.blocked_user_ids())

    def test_admin_cannot_be_blocked(self) -> None:
        self.assertFalse(access_control.block_user(100))
        self.assertNotIn(100, access_control.blocked_user_ids())


if __name__ == "__main__":
    unittest.main()
