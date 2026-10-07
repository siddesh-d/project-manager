import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from assistant.core import command_center
from assistant.services import web_server
from assistant.services.pm2_manager import parse_delete_logs


class TestRemoveLogs(unittest.TestCase):
    def test_delete_logs_option_is_opt_in_and_strictly_parsed(self):
        self.assertEqual(parse_delete_logs('delete mqtt'), ('delete mqtt', False))
        self.assertEqual(parse_delete_logs('delete mqtt --delete-logs'), ('delete mqtt', True))
        self.assertEqual(parse_delete_logs('remove mqtt --delete-logs'), ('remove mqtt', True))
        for command in ['delete mqtt --delete-logs extra', 'start mqtt --delete-logs', 'delete --delete-logs mqtt']:
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_delete_logs(command)

    def test_deletes_all_registered_instance_logs_only_after_pm2_success(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f'mqtt-{instance}-{kind}.log'
                     for instance in [3, 4] for kind in ['out', 'err', 'combined']]
            for path in paths:
                path.write_text('log', encoding='utf-8')
            processes = [
                {'name': 'mqtt', 'pm2_env': {
                    'pm_out_log_path': str(paths[index * 3]),
                    'pm_err_log_path': str(paths[index * 3 + 1]),
                    'pm_log_path': str(paths[index * 3 + 2]),
                }} for index in range(2)
            ] + [{'name': 'other', 'pm2_env': {'pm_out_log_path': str(Path(directory) / 'other.log')}}]
            with patch.object(command_center.subprocess, 'run', side_effect=[
                Mock(returncode=0, stdout=json.dumps(processes)), Mock(returncode=0)
            ]) as run:
                ok, message = command_center._delete_pm2_service('mqtt', delete_logs=True)
            self.assertTrue(ok)
            self.assertIn('log files deleted', message)
            self.assertEqual(run.call_args_list[1].args[0], f'{command_center.PM2_EXECUTABLE} delete mqtt')
            self.assertTrue(all(not path.exists() for path in paths))

    def test_default_delete_keeps_logs_and_failed_pm2_delete_keeps_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / 'service.log'
            log_path.write_text('log', encoding='utf-8')
            with patch.object(command_center.subprocess, 'run', return_value=Mock(returncode=0)) as run:
                ok, _ = command_center._delete_pm2_service('mqtt')
            self.assertTrue(ok)
            self.assertTrue(log_path.exists())
            self.assertEqual(run.call_count, 1)

            snapshot = Mock(returncode=0, stdout=json.dumps([
                {'name': 'mqtt', 'pm2_env': {'pm_out_log_path': str(log_path)}}
            ]))
            with patch.object(command_center.subprocess, 'run', side_effect=[snapshot, Mock(returncode=1)]):
                ok, message = command_center._delete_pm2_service('mqtt', delete_logs=True)
            self.assertFalse(ok)
            self.assertIn('logs were kept', message)
            self.assertTrue(log_path.exists())

    def test_cannot_delete_logs_if_pm2_registry_is_unavailable(self):
        with patch.object(command_center.subprocess, 'run', return_value=Mock(returncode=1, stdout='')) as run:
            ok, message = command_center._delete_pm2_service('mqtt', delete_logs=True)
        self.assertFalse(ok)
        self.assertIn('service was not removed', message)
        run.assert_called_once()

    def test_tenant_delete_preserves_checked_option_after_authorization(self):
        user = {'role': 'tenant_admin', 'tenant_id': 'tenant-a'}
        callback = Mock(return_value={'ok': True})
        with patch.object(web_server, '_get_project_for_user', return_value={'name': 'mqtt'}) as lookup:
            result = web_server._authorize_tenant_ui_command(user, 'delete mqtt --delete-logs', callback)
        self.assertTrue(result['ok'])
        lookup.assert_called_once_with('mqtt', user, require_manage=True)
        callback.assert_called_once_with('delete mqtt --delete-logs', 'tenant-a')

    def test_process_command_honors_checked_delete_option(self):
        with patch.object(command_center, 'resolve_pm2_target', return_value='mqtt'), patch.object(
            command_center, 'require_confirmation', return_value=True
        ), patch.object(command_center, '_delete_pm2_service', return_value=(True, 'removed')) as delete, patch.object(
            command_center, 'broadcast'
        ):
            command_center.process_command('delete mqtt --delete-logs', Mock())
        delete.assert_called_once_with('mqtt', delete_logs=True)

    def test_delete_logs_option_rejects_bulk_deletion(self):
        with patch.object(command_center, 'resolve_pm2_target') as resolve, patch.object(
            command_center, 'require_confirmation'
        ) as confirm:
            result = command_center.process_command('delete all --delete-logs', Mock())
        self.assertFalse(result['ok'])
        resolve.assert_not_called()
        confirm.assert_not_called()


if __name__ == '__main__':
    unittest.main()