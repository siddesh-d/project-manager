import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from jarvis_assistant.auth import (
    ROLE_DEFINITIONS,
    user_has_permission,
    user_has_scope_access,
)
from jarvis_assistant.registry import projects
from jarvis_assistant.core import command_center
from jarvis_assistant.services import web_server


class TestRBACPermissions(unittest.TestCase):
    def test_platform_admin_has_full_permissions(self):
        user = {
            "id": "platform-admin",
            "username": "platform-admin",
            "role": "platform_admin",
            "tenant_id": None,
            "project_ids": [],
        }

        for permission in ROLE_DEFINITIONS["platform_admin"]["permissions"]:
            self.assertTrue(user_has_permission(user, permission, tenant_id="tenant-a", project_id="project-1"))
        self.assertTrue(user_has_scope_access(user, tenant_id="tenant-b", project_id="project-9"))

    def test_tenant_admin_has_only_assigned_scope(self):
        user = {
            "id": "tenant-admin",
            "username": "tenant-admin",
            "role": "tenant_admin",
            "tenant_id": "tenant-a",
            "project_ids": ["project-1", "project-2"],
        }

        self.assertTrue(user_has_permission(user, "view_assigned_projects"))
        self.assertTrue(user_has_permission(user, "create_project_resources", tenant_id="tenant-a", project_id="project-1"))
        self.assertTrue(user_has_scope_access(user, tenant_id="tenant-a", project_id="project-1"))
        self.assertFalse(user_has_scope_access(user, tenant_id="tenant-b", project_id="project-5"))
        self.assertFalse(user_has_permission(user, "manage_platform_settings"))

    def test_tenant_user_is_read_only(self):
        user = {
            "id": "tenant-user",
            "username": "tenant-user",
            "role": "tenant_user",
            "tenant_id": "tenant-a",
            "project_ids": ["project-1"],
        }

        self.assertTrue(user_has_permission(user, "view_assigned_projects"))
        self.assertTrue(user_has_scope_access(user, tenant_id="tenant-a", project_id="project-1"))
        self.assertFalse(user_has_permission(user, "create_project_resources", tenant_id="tenant-a", project_id="project-1"))
        self.assertFalse(user_has_permission(user, "delete_project_resources", tenant_id="tenant-a", project_id="project-1"))
        self.assertFalse(user_has_permission(user, "manage_tenant_users", tenant_id="tenant-a"))

    def test_tenant_pm2_filter_hides_other_tenant_processes(self):
        user = {
            "id": "tenant-admin",
            "username": "tenant-admin",
            "role": "tenant_admin",
            "tenant_id": "tenant-a",
        }

        services = [
            {"name": "project-alpha", "status": "online"},
            {"name": "project-beta", "status": "online"},
            {"name": "project-gamma", "status": "online"},
        ]

        with patch.object(web_server, '_filter_projects_for_user', return_value=[{"name": "project-alpha"}, {"name": "project-gamma"}]):
            visible = web_server._filter_pm2_services_for_user(services, user)

        self.assertEqual([service["name"] for service in visible], ["project-alpha", "project-gamma"])

    def test_tenant_admin_start_all_only_starts_own_tenant_projects(self):
        user = {
            "id": "tenant-admin",
            "username": "tenant-admin",
            "role": "tenant_admin",
            "tenant_id": "tenant-a",
        }
        registry = [
            {"name": "tenant-a-api", "tenant_id": "tenant-a", "path": r"C:\tenant-a\api"},
            {"name": "tenant-b-api", "tenant_id": "tenant-b", "path": r"C:\tenant-b\api"},
            {"name": "tenant-a-worker", "tenant_id": "tenant-a", "path": r"C:\tenant-a\worker"},
        ]
        executed_commands = []

        def execute_command(command, tenant_id=None):
            executed_commands.append(command)
            target = command.split(' ', 1)[1]
            return {"type": "start_result", "target": target, "ok": True, "message": "started"}

        with web_server.app.test_request_context('/socket.io'), \
                patch.object(web_server, '_get_authenticated_user', return_value=user), \
                patch.object(web_server, '_ui_command_callback', execute_command), \
                patch.object(web_server.projects, 'get_projects', return_value=registry), \
                patch.object(web_server, 'get_tenant_core_project_path', return_value=r'C:\tenant-a'), \
                patch.object(web_server.socketio, 'emit'), \
                patch.object(web_server, 'stream_log_to_ui'):
            result = web_server.handle_incoming_ui_command({'command': 'start all'})

        self.assertTrue(result['ok'])
        self.assertEqual(executed_commands, ['start tenant-a-api', 'start tenant-a-worker'])
        self.assertEqual(result['started'], ['tenant-a-api', 'tenant-a-worker'])
        self.assertNotIn('start tenant-b-api', executed_commands)

    def test_tenant_admin_all_command_actions_are_tenant_scoped(self):
        user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
        registry = [
            {"name": "own-api", "tenant_id": "tenant-a", "path": r"C:\tenant-a\own-api"},
            {"name": "other-api", "tenant_id": "tenant-b", "path": r"C:\tenant-b\other-api"},
        ]
        executed_commands = []

        def execute_command(command, tenant_id=None):
            executed_commands.append(command)
            return {"ok": True}

        with patch.object(web_server.projects, 'get_projects', return_value=registry), \
            patch.object(web_server, 'get_tenant_core_project_path', return_value=r'C:\tenant-a'):
            for action in ('start', 'stop', 'restart', 'delete', 'flush'):
                denied = web_server._authorize_tenant_ui_command(user, f'{action} other-api', execute_command)
                self.assertFalse(denied['ok'], action)

                allowed = web_server._authorize_tenant_ui_command(user, f'{action} own-api', execute_command)
                self.assertTrue(allowed['ok'], action)

                bulk = web_server._authorize_tenant_ui_command(user, f'{action} all', execute_command)
                self.assertTrue(bulk['ok'], action)

        self.assertNotIn('start other-api', executed_commands)
        self.assertFalse(any(command.endswith(' other-api') for command in executed_commands))
        for action in ('start', 'stop', 'restart', 'delete', 'flush'):
            self.assertEqual(executed_commands.count(f'{action} own-api'), 2)

    def test_command_processor_denies_direct_pm2_fallback_for_other_tenant(self):
        registry = [
            {"name": "own-api", "friendly_name": "Own API", "tenant_id": "tenant-a", "path": r"C:\tenant-a\own-api"},
            {"name": "other-api", "friendly_name": "Other API", "tenant_id": "tenant-b", "path": r"C:\tenant-b\other-api"},
        ]

        for action in ('start', 'stop', 'restart', 'delete', 'flush'):
            with patch.object(command_center, 'get_projects', return_value=registry), \
                    patch.object(command_center, 'resolve_pm2_target', return_value='other-api'), \
                    patch.object(command_center.subprocess, 'run') as run:
                result = command_center.process_command(
                    f'{action} other-api',
                    voice=None,
                    tenant_id='tenant-a',
                )

            self.assertFalse(result['ok'], action)
            self.assertIn('access denied', result['message'].lower())
            run.assert_not_called()

    def test_tenant_project_visibility_requires_explicit_matching_tenant(self):
        user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
        registry = [
            {"name": "own", "tenant_id": "tenant-a"},
            {"name": "other", "tenant_id": "tenant-b"},
            {"name": "legacy-unowned", "path": r"C:\tenant-a\legacy"},
        ]

        visible = web_server._filter_projects_for_user(registry, user)

        self.assertEqual([project['name'] for project in visible], ['own'])

    def test_tenant_folder_browsing_cannot_escape_assigned_root(self):
        user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
        with tempfile.TemporaryDirectory() as tenant_root, tempfile.TemporaryDirectory() as other_root, \
                patch.object(web_server, 'get_tenant_core_project_path', return_value=tenant_root):
            allowed_path, allowed_error = web_server._tenant_browse_path(user, tenant_root)
            denied_path, denied_error = web_server._tenant_browse_path(user, other_root)

        self.assertEqual(allowed_path, tenant_root)
        self.assertIsNone(allowed_error)
        self.assertIsNone(denied_path)
        self.assertIn('access denied', denied_error.lower())

    def test_tenant_log_stream_rejects_other_tenant_project(self):
        user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
        registry = [{"name": "other-api", "tenant_id": "tenant-b"}]
        with web_server.app.test_request_context('/socket.io'), \
                patch.object(web_server, '_get_authenticated_user', return_value=user), \
                patch.object(web_server.projects, 'get_projects', return_value=registry), \
                patch.object(web_server, '_emit_to_request') as emit, \
                patch.object(web_server.subprocess, 'Popen') as popen:
            result = web_server.handle_toggle_logs({'service': 'other-api', 'action': 'start'})

        self.assertFalse(result['ok'])
        popen.assert_not_called()
        emit.assert_called_once()

    def test_tenant_project_update_rejects_other_tenant_project(self):
        user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
        registry = [{"name": "other-api", "tenant_id": "tenant-b"}]
        with web_server.app.test_request_context('/socket.io'), \
                patch.object(web_server, '_get_authenticated_user', return_value=user), \
                patch.object(web_server.projects, 'get_projects', return_value=registry), \
                patch.object(web_server.projects, 'update_project') as update_project, \
                patch.object(web_server, '_emit_to_request'):
            web_server.handle_update_project({'name': 'other-api', 'friendly_name': 'Compromised'})

        update_project.assert_not_called()

    def test_registry_rejects_tenant_project_outside_assigned_root(self):
        with tempfile.TemporaryDirectory() as temp_root:
            source_dir = os.path.join(temp_root, 'source')
            tenant_root = os.path.join(temp_root, 'tenant-root')
            other_root = os.path.join(temp_root, 'other-root')
            os.makedirs(source_dir)
            os.makedirs(tenant_root)
            os.makedirs(other_root)

            ok, error = projects.add_project(
                'outside-project',
                'Outside Project',
                source_dir,
                storage_mode='core',
                destination_path=other_root,
                tenant_id='tenant-a',
                tenant_root=tenant_root,
            )

        self.assertFalse(ok)
        self.assertIn('assigned tenant project path', error.lower())

    def test_registry_rejects_tenant_custom_shell_command(self):
        with tempfile.TemporaryDirectory() as temp_root:
            source_dir = os.path.join(temp_root, 'source')
            tenant_root = os.path.join(temp_root, 'tenant-root')
            os.makedirs(source_dir)
            os.makedirs(tenant_root)

            ok, error = projects.add_project(
                'shell-project',
                'Shell Project',
                source_dir,
                custom_start='arbitrary-command',
                storage_mode='core',
                destination_path=tenant_root,
                tenant_id='tenant-a',
                tenant_root=tenant_root,
            )

        self.assertFalse(ok)
        self.assertIn('custom shell', error.lower())

    def test_logout_invalidates_cached_socket_authorization(self):
        web_server._socket_user_map['tenant-sid'] = {'id': 'tenant-admin', 'tenant_id': 'tenant-a'}
        try:
            with web_server.app.test_request_context('/api/logout', method='POST'):
                web_server.session['user_id'] = 'tenant-admin'
                response = web_server.logout()

            self.assertTrue(response.get_json()['ok'])
            self.assertNotIn('tenant-sid', web_server._socket_user_map)
        finally:
            web_server._socket_user_map.pop('tenant-sid', None)

    def test_tenant_admin_forces_core_path_storage_only(self):
        user = {
            "id": "tenant-admin",
            "username": "tenant-admin",
            "role": "tenant_admin",
            "tenant_id": "tenant-a",
        }

        with patch.object(web_server, 'get_tenant_core_project_path', return_value=r'C:\tenant-a\core'):
            blocked = web_server._enforce_tenant_admin_project_constraints(
                user,
                source_path=r'C:\tenant-a\core\project-alpha',
                storage_mode='custom',
                destination_path=r'D:\outside'
            )
            self.assertFalse(blocked['ok'])
            self.assertIn('assigned core project path', blocked['error'].lower())

            allowed = web_server._enforce_tenant_admin_project_constraints(
                user,
                source_path=r'C:\tenant-a\core\project-alpha',
                storage_mode='core',
                destination_path=r'C:\tenant-a\core'
            )
            self.assertTrue(allowed['ok'])
            self.assertEqual(allowed['storage_mode'], 'core')

    def test_tenant_project_preferences_use_assigned_core_path(self):
        user = {
            "id": "tenant-admin",
            "username": "tenant-admin",
            "role": "tenant_admin",
            "tenant_id": "tenant-a",
        }

        with patch.object(web_server, '_emit_projects_list'), \
             patch.object(web_server, '_get_authenticated_user', return_value=user), \
             patch.object(web_server, 'get_tenant_core_project_path', return_value=r'C:\tenant-a\core'), \
             patch.object(web_server.projects, 'get_core_project_path', return_value=r'X:\global-core'), \
             patch.object(web_server.socketio, 'emit') as mock_emit:
            web_server.handle_get_projects()

        self.assertIn(
            ('project_preferences', {'core_project_path': r'C:\tenant-a\core'}),
            [(call.args[0], call.args[1]) for call in mock_emit.call_args_list]
        )

    def test_tenant_admin_add_project_records_tenant_scope(self):
        temp_root = tempfile.mkdtemp(prefix='jarvis-tenant-add-')
        original_file = projects.PROJECTS_FILE
        original_projects = projects._projects
        original_core_path = projects._core_project_path
        source_dir = os.path.join(temp_root, 'source-app')
        core_dir = os.path.join(temp_root, 'tenant-core')
        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(core_dir, exist_ok=True)

        try:
            projects.PROJECTS_FILE = os.path.join(temp_root, 'projects.json')
            projects._projects = []
            projects._core_project_path = core_dir

            ok, err = projects.add_project(
                'tenant-app',
                'Tenant App',
                source_dir,
                storage_mode='core',
                destination_path=core_dir,
                tenant_id='tenant-a',
                tenant_root=core_dir,
            )

            self.assertTrue(ok, err)
            stored = projects.get_projects()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]['tenant_id'], 'tenant-a')

            user = {
                'id': 'tenant-admin',
                'username': 'tenant-admin',
                'role': 'tenant_admin',
                'tenant_id': 'tenant-a',
            }
            visible = web_server._filter_projects_for_user(stored, user)
            self.assertEqual([item['name'] for item in visible], ['tenant-app'])
        finally:
            projects.PROJECTS_FILE = original_file
            projects._projects = original_projects
            projects._core_project_path = original_core_path
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_core_storage_uses_explicit_tenant_destination(self):
        source_path = r'C:\source\sample-app'
        target_path, error = projects._resolve_target_path(
            source_path,
            'core',
            destination_path=r'C:\tenant-a\core',
            core_project_path=r'X:\global-core'
        )

        self.assertIsNone(error)
        self.assertEqual(target_path, r'C:\tenant-a\core\sample-app')


if __name__ == "__main__":
    unittest.main()
