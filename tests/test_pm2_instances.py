import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from assistant.core import command_center
from assistant.services import web_server
from assistant.services.pm2_manager import parse_start_instances


class TestPm2Instances(unittest.TestCase):
    def test_telemetry_emits_cluster_counts_for_registered_external_and_amr_services(self):
        for name, registered in [('mqtt', True), ('external-api', False), ('amr-service-device-123', False)]:
            with self.subTest(name=name):
                workers = [{'name': name, 'pm2_env': {'status': 'online'}} for worker_index in range(2)]
                registry = [{'name': name, 'path': ''}] if registered else []
                user = {'id': 'admin', 'role': 'platform_admin'}
                with patch.object(web_server.subprocess, 'run', side_effect=[
                    Mock(returncode=0, stdout=json.dumps(workers)), Mock(returncode=1, stdout='')
                ]), patch.object(web_server.projects, 'get_projects', return_value=registry), patch.object(
                    web_server, 'get_port_from_env', return_value=7070
                ), patch.object(web_server, '_connected_socket_ids', {'test-sid'}), patch.object(
                    web_server, '_socket_user_map', {'test-sid': user}
                ), patch.object(web_server, 'get_user_by_id', return_value=user), patch.object(
                    web_server, '_filter_pm2_services_for_user', side_effect=lambda services, current_user: services
                ), patch.object(web_server, '_set_running_service_names'), patch.object(
                    web_server, '_last_pm2_status_map', {}
                ), patch.object(web_server.pm2_manager, 'get_host_metrics', return_value=None), patch.object(
                    web_server.socketio, 'emit'
                ) as emit, patch.object(web_server.time, 'sleep', side_effect=[None, RuntimeError('end loop')]):
                    with self.assertRaisesRegex(RuntimeError, 'end loop'):
                        web_server.pm2_telemetry_loop()
                self.assertEqual(emit.call_count, 2)
                for call in emit.call_args_list:
                    services = call.args[1]['services']
                    self.assertEqual(len(services), 1)
                    self.assertEqual(services[0]['instances'], 2)
                    self.assertEqual(services[0]['online_instances'], 2)

    def test_live_cluster_counts_workers_and_aggregates_metrics(self):
        workers = [
            {'name': 'mqtt', 'pm2_env': {'status': status, 'exec_mode': 'cluster_mode', 'instances': 99},
             'monit': {'cpu': 10, 'memory': 20 * 1024 * 1024}}
            for status in ['online', 'online']
        ]
        grouped = web_server._group_pm2_processes(workers)
        self.assertEqual(list(grouped), ['mqtt'])
        payload = web_server._build_pm2_service_payload(grouped['mqtt'])
        self.assertEqual(payload['instances'], 2)
        self.assertEqual(payload['online_instances'], 2)
        self.assertEqual(payload['cpu'], 20)
        self.assertEqual(payload['memory'], '40MB')

    def test_live_cluster_counts_only_online_workers(self):
        workers = [
            {'name': 'mqtt', 'pm2_env': {'status': status}}
            for status in ['stopped', 'online', 'errored', 'launching']
        ]
        payload = web_server._build_pm2_service_payload(web_server._group_pm2_processes(workers)['mqtt'])
        self.assertEqual(payload['instances'], 4)
        self.assertEqual(payload['online_instances'], 1)
        self.assertEqual(payload['status'], 'online')

    def test_fork_and_stopped_services_have_live_instance_counts(self):
        grouped = web_server._group_pm2_processes([
            {'name': 'api', 'pm2_env': {'status': 'online'}},
            {'name': 'worker', 'pm2_env': {'status': 'stopped'}},
            {'pm2_env': {'status': 'online'}},
        ])
        self.assertEqual(set(grouped), {'api', 'worker'})
        for name, online_count in [('api', 1), ('worker', 0)]:
            payload = web_server._build_pm2_service_payload(grouped[name])
            self.assertEqual(payload['instances'], 1)
            self.assertEqual(payload['online_instances'], online_count)

    def test_tenant_start_preserves_instances_after_authorization(self):
        user = {'role': 'tenant_admin', 'tenant_id': 'tenant-a'}
        callback = Mock(return_value={'ok': True})
        with patch.object(web_server, '_get_project_for_user', return_value={'name': 'api'}) as lookup:
            result = web_server._authorize_tenant_ui_command(user, 'start api --instances 3', callback)
        self.assertTrue(result['ok'])
        lookup.assert_called_once_with('api', user, require_manage=True)
        callback.assert_called_once_with('start api --instances 3', 'tenant-a')

    def test_tenant_start_denies_other_project(self):
        callback = Mock()
        with patch.object(web_server, '_get_project_for_user', return_value=None):
            result = web_server._authorize_tenant_ui_command({'tenant_id': 'tenant-a'}, 'start private --instances 3', callback)
        self.assertFalse(result['ok'])
        callback.assert_not_called()

    def test_process_command_routes_count_to_start(self):
        project = {'name': 'api', 'friendly_name': 'API', 'tenant_id': 'tenant-a'}
        with patch.object(command_center, 'get_projects', return_value=[project]), patch.object(
            command_center, 'resolve_pm2_target', return_value='api'
        ), patch.object(command_center, 'intelligent_service_start', return_value=True) as start:
            voice = Mock()
            result = command_center.process_command('start api --instances 3', voice, tenant_id='tenant-a')
        self.assertTrue(result['ok'])
        start.assert_called_once_with(project, voice, None, instances=3)

    def test_parse_start_instances(self):
        self.assertEqual(parse_start_instances('start api --instances 4'), ('start api', 4))
        self.assertEqual(parse_start_instances('start api'), ('start api', None))
        for value in ['0', '-1', '1.5', 'all', '2;whoami', '']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_start_instances(f'start api --instances {value}')

    def test_runtime_and_fallback_commands_include_instances(self):
        for entry in ['server.js', '']:
            for instances in [None, 1, 4]:
                with self.subTest(entry=entry, instances=instances), tempfile.TemporaryDirectory() as tmpdir:
                    target = Path(tmpdir) / (entry or 'dist/main.js')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                    project = {'name': 'api', 'friendly_name': 'API', 'path': tmpdir,
                               'deployment_profile': {'project_type': 'node', 'runtime_entry': entry}}
                    with patch.object(command_center, 'refresh_project_deployment_profile', return_value=project), patch.object(
                        command_center, '_prepare_project_runtime', return_value=True
                    ), patch.object(command_center, 'broadcast'), patch.object(command_center.subprocess, 'run'), patch.object(
                        command_center, '_start_pm2_entry', return_value=(True, '')
                    ) as start:
                        self.assertTrue(command_center.intelligent_service_start(project, Mock(), None, instances=instances))
                    command = start.call_args.args[2]
                    if instances is None:
                        self.assertNotIn('--instances', command)
                    else:
                        self.assertIn(f'--instances {instances}', command)

    def test_invalid_or_unsupported_request_does_not_delete_service(self):
        for instances, profile, custom in [(0, 'node', False), (True, 'node', False), (2, 'python', False), (2, 'node', True)]:
            project = {'name': 'api', 'friendly_name': 'API', 'path': '.', 'deployment_profile': {'project_type': profile}}
            if custom:
                project['custom_start'] = 'npm start'
            with self.subTest(instances=instances, profile=profile, custom=custom), patch.object(
                command_center, 'refresh_project_deployment_profile', return_value=project
            ), patch.object(command_center, 'broadcast'), patch.object(command_center, 'update_runtime_state'), patch.object(
                command_center.subprocess, 'run'
            ) as run:
                self.assertFalse(command_center.intelligent_service_start(project, Mock(), None, instances=instances))
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()