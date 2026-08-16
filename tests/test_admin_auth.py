import json
import os
import tempfile
import unittest
from pathlib import Path

from jarvis_assistant.auth import ensure_default_admin_user, verify_user, get_user_store_path, normalize_role_name


class TestAdminAuth(unittest.TestCase):
    def test_admin_user_exists_and_uses_hashed_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_store = os.environ.get("JARVIS_USERS_FILE")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            try:
                store = ensure_default_admin_user()
                self.assertIn("users", store)
                admin = store["users"][0]
                self.assertEqual(admin["username"], "admin")
                self.assertEqual(normalize_role_name(admin["role"]), "platform_admin")
                self.assertEqual(admin["role"], "platform_admin")
                self.assertNotEqual(admin.get("password"), "admin")
                self.assertIn("password_hash", admin)
                self.assertTrue(verify_user("admin", "admin"))
                self.assertFalse(verify_user("admin", "wrong-pass"))
                self.assertTrue(Path(get_user_store_path("admin")).exists() or Path(os.environ["JARVIS_USERS_FILE"]).exists())
            finally:
                if original_store is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_store


if __name__ == "__main__":
    unittest.main()
