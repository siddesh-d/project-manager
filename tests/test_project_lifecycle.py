import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant.core import command_center
from assistant.registry import projects
from assistant.services import web_server


class TestProjectLifecycle(unittest.TestCase):
    def test_load_projects_preserves_tenant_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_file = Path(tmpdir) / "projects.json"
            payload = {
                "core_project_path": "",
                "projects": [
                    {
                        "name": "tenant-api",
                        "friendly_name": "Tenant API",
                        "path": tmpdir,
                        "tenant_id": "tenant-a",
                    }
                ],
            }
            projects_file.write_text(json.dumps(payload), encoding="utf-8")

            original_projects_file = projects.PROJECTS_FILE
            original_cache = projects._projects
            original_core = projects._core_project_path
            try:
                projects.PROJECTS_FILE = str(projects_file)
                projects._projects = None
                loaded = projects.load_projects()
            finally:
                projects.PROJECTS_FILE = original_projects_file
                projects._projects = original_cache
                projects._core_project_path = original_core

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].get("tenant_id"), "tenant-a")

    def test_load_projects_marks_inaccessible_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = str(Path(tmpdir) / "missing")
            projects_file = Path(tmpdir) / "projects.json"
            payload = {
                "core_project_path": "",
                "projects": [
                    {
                        "name": "broken-service",
                        "friendly_name": "Broken Service",
                        "path": missing_path,
                    }
                ],
            }
            projects_file.write_text(json.dumps(payload), encoding="utf-8")

            original_projects_file = projects.PROJECTS_FILE
            original_cache = projects._projects
            original_core = projects._core_project_path
            try:
                projects.PROJECTS_FILE = str(projects_file)
                projects._projects = None
                loaded = projects.load_projects()
            finally:
                projects.PROJECTS_FILE = original_projects_file
                projects._projects = original_cache
                projects._core_project_path = original_core

        self.assertEqual(loaded[0].get("runtime_state", {}).get("last_error_stage"), "path")
        self.assertIn("not accessible", loaded[0].get("runtime_state", {}).get("last_error", ""))

    def test_prepare_install_command_reports_missing_npm(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(command_center, "_resolve_executable", return_value=None):
            command, error = command_center._prepare_install_command(
                ["npm", "ci"],
                "node",
                tmpdir,
                extra_env={},
            )

        self.assertIsNone(command)
        self.assertIn("npm is not installed", (error or "").lower())

    def test_project_file_route_blocks_path_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
            project = {"name": "svc", "path": tmpdir, "tenant_id": "tenant-a"}
            with web_server.app.test_request_context(
                "/api/projects/svc/file",
                method="PUT",
                json={"path": "../outside.txt", "content": "blocked"},
            ), patch.object(web_server, "_get_authenticated_user", return_value=user), patch.object(
                web_server, "_get_project_for_user", return_value=project
            ):
                response, status = web_server.write_project_file("svc")

        self.assertEqual(status, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("traversal", payload["error"].lower())

    def test_project_file_route_saves_and_reads_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
            project = {"name": "svc", "path": tmpdir, "tenant_id": "tenant-a"}
            target = Path(tmpdir) / "notes.txt"
            target.write_text("old", encoding="utf-8")

            with web_server.app.test_request_context(
                "/api/projects/svc/file",
                method="PUT",
                json={"path": "notes.txt", "content": "new text"},
            ), patch.object(web_server, "_get_authenticated_user", return_value=user), patch.object(
                web_server, "_get_project_for_user", return_value=project
            ):
                response = web_server.write_project_file("svc")

            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "new text")

            with web_server.app.test_request_context(
                "/api/projects/svc/file?path=notes.txt",
                method="GET",
            ), patch.object(web_server, "_get_authenticated_user", return_value=user), patch.object(
                web_server, "_get_project_for_user", return_value=project
            ):
                read_response = web_server.read_project_file("svc")

            read_payload = read_response.get_json()
            self.assertTrue(read_payload["ok"])
            self.assertEqual(read_payload["content"], "new text")


if __name__ == "__main__":
    unittest.main()
