import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from assistant.services import web_server


class TestLogDownload(unittest.TestCase):
    def test_lists_and_downloads_each_cluster_log(self):
        with tempfile.TemporaryDirectory() as directory:
            workers = []
            for instance in [5, 6]:
                env = {}
                for kind, field in [('output', 'pm_out_log_path'), ('error', 'pm_err_log_path')]:
                    path = Path(directory) / f'mqtt-{kind}-{instance}.log'
                    path.write_bytes(f'{instance} {kind}\n'.encode())
                    env[field] = str(path)
                workers.append({'name': 'mqtt', 'pm_id': instance, 'pm2_env': env})
            result = Mock(returncode=0, stdout='PM2 notice\n' + json.dumps(workers))
            with patch.object(web_server, '_get_authenticated_user', return_value={'role': 'platform_admin'}), patch.object(
                web_server.subprocess, 'run', return_value=result
            ):
                client = web_server.app.test_client()
                response = client.get('/api/services/mqtt/logs')
                entries = response.get_json()['files']
                self.assertEqual(len(entries), 4)
                self.assertEqual({entry['instance'] for entry in entries}, {5, 6})
                for entry in entries:
                    self.assertNotIn('path', entry)
                    download = client.get('/api/services/mqtt/logs', query_string={'file': entry['id']})
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(download.data, f"{entry['instance']} {entry['type']}\n".encode())
                    self.assertIn('attachment', download.headers['Content-Disposition'])
                    download.close()
                self.assertEqual(client.get('/api/services/mqtt/logs?file=../../users.json').status_code, 404)

    def test_access_is_checked_for_listing_and_download(self):
        for user, allowed, status in [(None, False, 401), ({'role': 'tenant_view_user'}, False, 404),
                                      ({'role': 'tenant_view_user'}, True, 200)]:
            for query in ['', '?file=invalid']:
                with self.subTest(user=user, query=query), patch.object(
                    web_server, '_get_authenticated_user', return_value=user
                ), patch.object(web_server, '_get_project_for_user', return_value={'name': 'api'} if allowed else None), patch.object(
                    web_server, '_get_pm2_log_files', return_value=[]
                ) as lookup, patch.object(web_server, '_require_scope_access', return_value=True):
                    response = web_server.app.test_client().get('/api/services/api/logs' + query)
                    self.assertEqual(response.status_code, 404 if allowed and query else status)
                    if not allowed:
                        lookup.assert_not_called()

    def test_missing_files_and_other_services_are_not_listed(self):
        result = Mock(returncode=0, stdout=json.dumps([
            {'name': 'api', 'pm2_env': {'pm_out_log_path': 'missing-file.log'}},
            {'name': 'other', 'pm2_env': {'pm_out_log_path': __file__}},
        ]))
        with patch.object(web_server.subprocess, 'run', return_value=result):
            self.assertEqual(web_server._get_pm2_log_files('api'), [])

    def test_pm2_failure_returns_error(self):
        with patch.object(web_server, '_get_authenticated_user', return_value={'role': 'platform_admin'}), patch.object(
            web_server.subprocess, 'run', return_value=Mock(returncode=1, stdout='')
        ):
            response = web_server.app.test_client().get('/api/services/api/logs')
            self.assertEqual(response.status_code, 503)