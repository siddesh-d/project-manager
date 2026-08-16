import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import session

from jarvis_assistant.auth import (
    create_tenant_registration,
    get_tenant_by_id,
    get_tenant_core_project_path,
    get_tenant_user_store,
    user_has_permission,
)
from jarvis_assistant.services import web_server


class TestTenantRegistration(unittest.TestCase):
    def test_platform_admin_can_register_tenant_and_initial_user(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                store = {
                    "users": [{
                        "id": "admin",
                        "username": "admin",
                        "role": "platform_admin",
                        "password_hash": "scrypt:32768:8:1$abc$def",
                    }]
                }
                with open(os.environ["JARVIS_USERS_FILE"], "w", encoding="utf-8") as handle:
                    import json
                    json.dump(store, handle)

                tenant = create_tenant_registration(
                    tenant_name="Acme Labs",
                    admin_username="tenant-admin",
                    admin_password="StrongPass!23",
                    created_by="admin",
                )

                self.assertIn("tenant_id", tenant)
                self.assertIn("user", tenant)
                self.assertEqual(tenant["user"]["tenant_id"], tenant["tenant_id"])
                self.assertEqual(tenant["user"]["role"], "tenant_admin")
                self.assertTrue(Path(get_tenant_core_project_path(tenant["tenant_id"])).exists())
                self.assertTrue(user_has_permission(tenant["user"], "view_assigned_projects", tenant_id=tenant["tenant_id"]))
                self.assertFalse(user_has_permission(tenant["user"], "manage_platform_settings"))
                self.assertIn(tenant["tenant_id"], get_tenant_user_store())
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir

    def test_tenant_user_cannot_set_core_project_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                tenant = create_tenant_registration(
                    tenant_name="Example",
                    admin_username="owner",
                    admin_password="Passw0rd!",
                    created_by="admin",
                )
                user = tenant["user"]
                self.assertFalse(user_has_permission(user, "manage_core_project_path", tenant_id=tenant["tenant_id"]))
                self.assertIsNotNone(get_tenant_by_id(tenant["tenant_id"]))
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir

    def test_tenant_admin_cannot_register_tenant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                with open(os.environ["JARVIS_USERS_FILE"], "w", encoding="utf-8") as handle:
                    import json
                    json.dump({
                        "users": [{
                            "id": "admin",
                            "username": "admin",
                            "role": "platform_admin",
                            "password_hash": "scrypt:32768:8:1$abc$def",
                        }, {
                            "id": "tenant-admin",
                            "username": "tenant-admin",
                            "role": "tenant_admin",
                            "tenant_id": "tenant-a",
                            "password_hash": "scrypt:32768:8:1$abc$def",
                        }]
                    }, handle)

                with self.assertRaises(PermissionError):
                    create_tenant_registration(
                        tenant_name="Blocked Tenant",
                        admin_username="tenant-owner",
                        admin_password="Passw0rd!",
                        actor={"role": "tenant_admin"},
                    )
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir

    def test_platform_admin_can_list_and_manage_existing_tenants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_tenants = os.environ.get("JARVIS_TENANTS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_TENANTS_FILE"] = str(Path(tmpdir) / "tenants.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                with open(os.environ["JARVIS_USERS_FILE"], "w", encoding="utf-8") as handle:
                    import json
                    json.dump({
                        "users": [{
                            "id": "admin",
                            "username": "admin",
                            "role": "platform_admin",
                            "password_hash": "scrypt:32768:8:1$abc$def",
                        }]
                    }, handle)

                tenant = create_tenant_registration(
                    tenant_name="Alpha Corp",
                    admin_username="alpha-admin",
                    admin_password="Passw0rd!",
                    created_by="admin",
                )
                from jarvis_assistant.services.web_server import app
                app.config["TESTING"] = True
                client = app.test_client()
                login = client.post("/api/login", json={"username": "admin", "password": "admin"})
                self.assertEqual(login.status_code, 200)

                list_response = client.get("/api/tenants")
                self.assertEqual(list_response.status_code, 200)
                self.assertTrue(any(item.get("id") == tenant["tenant_id"] for item in list_response.get_json().get("tenants", [])))

                detail_response = client.get(f"/api/tenants/{tenant['tenant_id']}")
                self.assertEqual(detail_response.status_code, 200)
                detail = detail_response.get_json()["tenant"]
                self.assertEqual(detail["name"], "Alpha Corp")

                update_response = client.put(f"/api/tenants/{tenant['tenant_id']}", json={"name": "Alpha Corp Updated"})
                self.assertEqual(update_response.status_code, 200)
                self.assertEqual(update_response.get_json()["tenant"]["name"], "Alpha Corp Updated")
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_tenants is None:
                    os.environ.pop("JARVIS_TENANTS_FILE", None)
                else:
                    os.environ["JARVIS_TENANTS_FILE"] = original_tenants
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir

    def test_platform_admin_can_register_tenant_with_core_project_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_tenants = os.environ.get("JARVIS_TENANTS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            original_tenant_dir = os.environ.get("JARVIS_TENANT_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_TENANTS_FILE"] = str(Path(tmpdir) / "tenants.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            os.environ["JARVIS_TENANT_CONFIG_DIR"] = str(Path(tmpdir) / "tenants")
            try:
                custom_path = str(Path(tmpdir) / "custom-core")
                tenant = create_tenant_registration(
                    tenant_name="Gamma Tenant",
                    admin_username="gamma-admin",
                    admin_password="Passw0rd!",
                    created_by="admin",
                    core_project_path=custom_path,
                )
                self.assertEqual(tenant["tenant"]["core_project_path"], custom_path)
                self.assertTrue(Path(custom_path).exists())
                self.assertEqual(tenant["tenant_id"], "gamma-tenant")
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_tenants is None:
                    os.environ.pop("JARVIS_TENANTS_FILE", None)
                else:
                    os.environ["JARVIS_TENANTS_FILE"] = original_tenants
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir
                if original_tenant_dir is None:
                    os.environ.pop("JARVIS_TENANT_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_TENANT_CONFIG_DIR"] = original_tenant_dir

    def test_tenant_admin_can_manage_only_own_tenant_users(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_tenants = os.environ.get("JARVIS_TENANTS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_TENANTS_FILE"] = str(Path(tmpdir) / "tenants.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                tenant = create_tenant_registration(
                    tenant_name="Gamma Tenant",
                    admin_username="gamma-admin",
                    admin_password="Passw0rd!",
                    created_by="admin",
                )
                from jarvis_assistant.services.web_server import app
                app.config["TESTING"] = True
                client = app.test_client()
                login = client.post("/api/login", json={"username": "gamma-admin", "password": "Passw0rd!"})
                self.assertEqual(login.status_code, 200)

                users_response = client.get(f"/api/tenants/{tenant['tenant_id']}/users")
                self.assertEqual(users_response.status_code, 200)

                view_user_response = client.post(f"/api/tenants/{tenant['tenant_id']}/users", json={
                    "username": "gamma-viewer",
                    "password": "Passw0rd!",
                    "role": "tenant_view_user",
                })
                self.assertEqual(view_user_response.status_code, 200, view_user_response.get_data(as_text=True))
                self.assertEqual(view_user_response.get_json()["user"]["role"], "tenant_view_user")

                admin_user_response = client.post(f"/api/tenants/{tenant['tenant_id']}/users", json={
                    "username": "gamma-admin-2",
                    "password": "Passw0rd!",
                    "role": "tenant_admin",
                })
                self.assertEqual(admin_user_response.status_code, 403)

                another_tenant_response = client.get("/api/tenants")
                self.assertEqual(another_tenant_response.status_code, 403)
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_tenants is None:
                    os.environ.pop("JARVIS_TENANTS_FILE", None)
                else:
                    os.environ["JARVIS_TENANTS_FILE"] = original_tenants
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir

    def test_tenant_user_cannot_access_platform_tenant_management(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_tenants = os.environ.get("JARVIS_TENANTS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_TENANTS_FILE"] = str(Path(tmpdir) / "tenants.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                tenant = create_tenant_registration(
                    tenant_name="Beta Tenant",
                    admin_username="beta-admin",
                    admin_password="Passw0rd!",
                    created_by="admin",
                )
                from jarvis_assistant.services.web_server import app
                app.config["TESTING"] = True
                client = app.test_client()
                login = client.post("/api/login", json={"username": "beta-admin", "password": "Passw0rd!"})
                self.assertEqual(login.status_code, 200)

                tenants_response = client.get("/api/tenants")
                self.assertEqual(tenants_response.status_code, 403)
                register_response = client.post("/api/tenants/register", json={"tenant_name": "Nope", "admin_username": "nope", "admin_password": "Password!1"})
                self.assertEqual(register_response.status_code, 403)

                core_response = client.put(f"/api/tenants/{tenant['tenant_id']}/core-path", json={"core_project_path": "C:/tmp/blocked"})
                self.assertEqual(core_response.status_code, 403)
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_tenants is None:
                    os.environ.pop("JARVIS_TENANTS_FILE", None)
                else:
                    os.environ["JARVIS_TENANTS_FILE"] = original_tenants
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir

    def test_platform_admin_can_delete_tenant_and_its_users(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_tenants = os.environ.get("JARVIS_TENANTS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_TENANTS_FILE"] = str(Path(tmpdir) / "tenants.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                with open(os.environ["JARVIS_USERS_FILE"], "w", encoding="utf-8") as handle:
                    import json
                    json.dump({
                        "users": [{
                            "id": "admin",
                            "username": "admin",
                            "role": "platform_admin",
                            "password_hash": "scrypt:32768:8:1$abc$def",
                        }]
                    }, handle)

                tenant = create_tenant_registration(
                    tenant_name="Alpha Tenant",
                    admin_username="alpha-admin",
                    admin_password="Passw0rd!",
                    created_by="admin",
                )
                from jarvis_assistant.auth import add_tenant_user
                add_tenant_user(tenant["tenant_id"], "alpha-user", "Passw0rd!", role="tenant_user", actor={"role": "platform_admin"})

                import jarvis_assistant.auth as auth_module
                with web_server.app.test_client() as client:
                    with client.session_transaction() as session_obj:
                        session_obj["user_id"] = "admin"
                    response = client.delete(f"/api/tenants/{tenant['tenant_id']}")
                    payload = response.get_json()
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(payload["ok"])
                    self.assertIsNone(get_tenant_by_id(tenant["tenant_id"]))
                    self.assertEqual(auth_module.get_tenant_users(tenant["tenant_id"]), [])
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_tenants is None:
                    os.environ.pop("JARVIS_TENANTS_FILE", None)
                else:
                    os.environ["JARVIS_TENANTS_FILE"] = original_tenants
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir

    def test_tenant_user_is_blocked_from_destructive_backend_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_users = os.environ.get("JARVIS_USERS_FILE")
            original_tenants = os.environ.get("JARVIS_TENANTS_FILE")
            original_config_dir = os.environ.get("JARVIS_USER_CONFIG_DIR")
            os.environ["JARVIS_USERS_FILE"] = str(Path(tmpdir) / "users.json")
            os.environ["JARVIS_TENANTS_FILE"] = str(Path(tmpdir) / "tenants.json")
            os.environ["JARVIS_USER_CONFIG_DIR"] = str(Path(tmpdir) / "users")
            try:
                tenant = create_tenant_registration(
                    tenant_name="Gamma Tenant",
                    admin_username="gamma-admin",
                    admin_password="Passw0rd!",
                    created_by="admin",
                )
                tenant_user = next(
                    user for user in __import__("json").loads(Path(os.environ["JARVIS_USERS_FILE"]).read_text(encoding="utf-8"))['users']
                    if user.get('tenant_id') == tenant['tenant_id'] and user.get('role') == 'tenant_admin'
                )
                with web_server.app.test_request_context('/'):
                    session.clear()
                    session['user_id'] = tenant_user['id']
                    web_server.socketio.emit = MagicMock()
                    web_server.handle_shutdown_app()
                    emitted = web_server.socketio.emit.call_args[0][1]
                    self.assertFalse(emitted.get('ok', True))

                    web_server.socketio.emit = MagicMock()
                    web_server.handle_set_core_project_path({'path': 'C:/tmp/should-fail'})
                    emitted = web_server.socketio.emit.call_args[0][1]
                    self.assertFalse(emitted.get('ok'))

                    web_server.socketio.emit = MagicMock()
                    web_server.handle_remove_project({'name': 'demo-project'})
                    emitted = web_server.socketio.emit.call_args[0][1]
                    self.assertFalse(emitted.get('ok'))

                    web_server.socketio.emit = MagicMock()
                    web_server.handle_delete_project_from_core({'name': 'demo-project'})
                    emitted = web_server.socketio.emit.call_args[0][1]
                    self.assertFalse(emitted.get('ok'))
            finally:
                if original_users is None:
                    os.environ.pop("JARVIS_USERS_FILE", None)
                else:
                    os.environ["JARVIS_USERS_FILE"] = original_users
                if original_tenants is None:
                    os.environ.pop("JARVIS_TENANTS_FILE", None)
                else:
                    os.environ["JARVIS_TENANTS_FILE"] = original_tenants
                if original_config_dir is None:
                    os.environ.pop("JARVIS_USER_CONFIG_DIR", None)
                else:
                    os.environ["JARVIS_USER_CONFIG_DIR"] = original_config_dir


if __name__ == "__main__":
    unittest.main()
