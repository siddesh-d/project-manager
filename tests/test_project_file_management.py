import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant.services import web_server


class TestProjectFileManagement(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / 'project'
        self.root.mkdir()
        self.project = {'name': 'svc', 'path': str(self.root), 'tenant_id': 'tenant-a'}
        self.user = {'role': 'tenant_admin', 'tenant_id': 'tenant-a'}
        self.auth_patch = patch.object(web_server, '_get_authenticated_user', return_value=self.user)
        self.project_patch = patch.object(web_server, '_get_project_for_user', return_value=self.project)
        self.auth_patch.start()
        self.project_patch.start()
        self.addCleanup(self.auth_patch.stop)
        self.addCleanup(self.project_patch.stop)

    def tearDown(self):
        self.tempdir.cleanup()

    def call(self, endpoint, method, path=None, payload=None):
        if method == 'GET':
            with web_server.app.test_request_context(endpoint, query_string={'path': path or ''}):
                result = web_server.list_project_files('svc')
                return result if isinstance(result, tuple) else (result, result.status_code)
        with web_server.app.test_request_context(endpoint, method=method, query_string={'path': path or ''}, json=payload):
            if endpoint.endswith('/file'):
                result = {
                    'POST': web_server.create_project_file,
                    'PUT': web_server.write_project_file,
                    'DELETE': web_server.delete_project_file,
                }[method]('svc')
            else:
                result = web_server.manage_project_folder('svc')
            return result if isinstance(result, tuple) else (result, result.status_code)

    def test_create_edit_replace_and_delete_file_within_root(self):
        response, status = self.call('/api/projects/svc/file', 'POST', payload={'path': 'src/app.txt', 'content': 'first'})
        self.assertEqual(status, 400)
        self.assertFalse((self.root / 'src').exists())

        (self.root / 'src').mkdir()
        response, status = self.call('/api/projects/svc/file', 'POST', payload={'path': 'src/app.txt', 'content': 'first'})
        self.assertEqual(status, 201)
        self.assertEqual((self.root / 'src/app.txt').read_text(encoding='utf-8'), 'first')

        _, status = self.call('/api/projects/svc/file', 'POST', payload={'path': 'src/app.txt', 'content': 'duplicate'})
        self.assertEqual(status, 409)
        response, status = self.call('/api/projects/svc/file', 'PUT', payload={'path': 'src/app.txt', 'content': 'replacement'})
        self.assertTrue(response.get_json()['ok'])
        self.assertEqual((self.root / 'src/app.txt').read_text(encoding='utf-8'), 'replacement')

        response, _ = self.call('/api/projects/svc/file', 'DELETE', path='src/app.txt')
        self.assertTrue(response.get_json()['ok'])
        self.assertFalse((self.root / 'src/app.txt').exists())

    def test_create_and_recursively_delete_folder(self):
        response, status = self.call('/api/projects/svc/folder', 'POST', payload={'path': 'src/components'})
        self.assertEqual(status, 400)
        (self.root / 'src').mkdir()
        response, status = self.call('/api/projects/svc/folder', 'POST', payload={'path': 'src/components'})
        self.assertEqual(status, 201)
        nested = self.root / 'src/components/nested'
        nested.mkdir()
        (nested / 'file.txt').write_text('data', encoding='utf-8')

        response, _ = self.call('/api/projects/svc/folder', 'DELETE', path='src/components')
        self.assertTrue(response.get_json()['ok'])
        self.assertFalse((self.root / 'src/components').exists())

    def test_rejects_traversal_and_project_root_deletion(self):
        for method, endpoint, path in [
            ('POST', '/api/projects/svc/file', '../outside.txt'),
            ('DELETE', '/api/projects/svc/file', '../outside.txt'),
            ('POST', '/api/projects/svc/folder', '../outside'),
            ('DELETE', '/api/projects/svc/folder', '../outside'),
            ('DELETE', '/api/projects/svc/folder', ''),
        ]:
            with self.subTest(method=method, path=path):
                if method == 'POST':
                    response, status = self.call(endpoint, method, payload={'path': path, 'content': 'x'}) if endpoint.endswith('/file') else self.call(endpoint, method, payload={'path': path})
                else:
                    response, status = self.call(endpoint, method, path=path)
                if method == 'POST':
                    self.assertEqual(status, 400)
                else:
                    self.assertIn(status, (400, 404))
        self.assertFalse((Path(self.tempdir.name) / 'outside.txt').exists())

    def test_symlink_to_outside_is_rejected_for_mutation(self):
        outside = Path(self.tempdir.name) / 'outside.txt'
        outside.write_text('keep', encoding='utf-8')
        link = self.root / 'outside-link.txt'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks are unavailable in this environment.')
        response, status = self.call('/api/projects/svc/file', 'DELETE', path='outside-link.txt')
        self.assertEqual(status, 400)
        self.assertEqual(outside.read_text(encoding='utf-8'), 'keep')

    def test_folder_alias_to_project_root_cannot_delete_root(self):
        alias = self.root / 'root-alias'
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks are unavailable in this environment.')
        (self.root / 'keep.txt').write_text('keep', encoding='utf-8')
        response, status = self.call('/api/projects/svc/folder', 'DELETE', path='root-alias')
        self.assertEqual(status, 400)
        self.assertTrue((self.root / 'keep.txt').exists())

    def test_non_manager_cannot_mutate_files_or_folders(self):
        with patch.object(web_server, '_user_can_manage_projects', return_value=False):
            response, status = self.call('/api/projects/svc/file', 'POST', payload={'path': 'new.txt'})
            self.assertEqual(status, 403)
            response, status = self.call('/api/projects/svc/folder', 'POST', payload={'path': 'new-folder'})
            self.assertEqual(status, 403)


if __name__ == '__main__':
    unittest.main()
