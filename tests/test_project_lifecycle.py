import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant.core import command_center
from assistant.services import project_runtime
from assistant.registry import projects
from assistant.services import web_server


class TestProjectLifecycle(unittest.TestCase):
    def test_upload_of_prebuilt_vite_project_registers_with_build_free_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_file = Path(tmpdir) / "projects.json"
            core_dir = Path(tmpdir) / "core"
            user = {"id": "u1", "role": "platform_admin"}
            files = {
                "react/package.json": json.dumps({"scripts": {
                    "build": "tsc && vite build",
                    "start:prod": "pm2 start ecosystem.config.js",
                }}),
                "react/build/index.html": "<html></html>",
                "react/.env": "PORT=3100",
            }
            data = {
                "name": "react",
                "storage_mode": "core",
                "destination_path": str(core_dir),
                "project_files": [(io.BytesIO(body.encode()), rel) for rel, body in files.items()],
            }

            original = (projects.PROJECTS_FILE, projects._projects, projects._core_project_path)
            try:
                projects.PROJECTS_FILE = str(projects_file)
                projects._projects = []
                projects._core_project_path = str(core_dir)
                with web_server.app.test_request_context(
                    "/api/upload_project", method="POST", data=data, content_type="multipart/form-data"
                ), patch.object(web_server, "_get_authenticated_user", return_value=user), patch.object(
                    web_server, "_emit_projects_list"
                ):
                    response = web_server.upload_project_from_device()
                added = projects.get_projects()[0]
            finally:
                projects.PROJECTS_FILE, projects._projects, projects._core_project_path = original

        self.assertTrue(response.get_json()["ok"])
        profile = added["deployment_profile"]
        self.assertEqual(profile["runtime_entry"], "build/index.html")
        self.assertFalse(profile["auto_install"])
        self.assertFalse(profile["auto_build"])
        self.assertEqual(added["custom_start"], "npm run start:prod")

    def test_new_prebuilt_vite_project_uses_package_pm2_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "build").mkdir()
            (project_path / "build" / "index.html").write_text("<html></html>", encoding="utf-8")
            (project_path / "ecosystem.config.js").write_text("module.exports = {};", encoding="utf-8")
            (project_path / "package.json").write_text(json.dumps({
                "scripts": {
                    "build": "cross-env NODE_ENV=production tsc && vite build",
                    "start:prod": "pm2 start ecosystem.config.js --update-env",
                },
            }), encoding="utf-8")

            original_projects_file = projects.PROJECTS_FILE
            original_cache = projects._projects
            original_core = projects._core_project_path
            try:
                projects.PROJECTS_FILE = str(project_path / "projects.json")
                projects._projects = []
                projects._core_project_path = ""
                ok, error = projects.add_project("vite-app", "Vite App", tmpdir)
                self.assertTrue(ok, error)
                added = projects.get_projects()[0]
            finally:
                projects.PROJECTS_FILE = original_projects_file
                projects._projects = original_cache
                projects._core_project_path = original_core

        profile = added["deployment_profile"]
        self.assertEqual(profile["build_policy"], "never")
        self.assertEqual(profile["runtime_entry"], "build/index.html")
        self.assertFalse(profile["auto_install"])
        self.assertFalse(profile["auto_build"])
        self.assertEqual(added["custom_start"], "npm run start:prod")

    def test_existing_node_profile_keeps_its_saved_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "build").mkdir()
            (path / "build" / "index.html").write_text("<html></html>", encoding="utf-8")
            (path / "ecosystem.config.js").write_text("module.exports = {};", encoding="utf-8")
            (path / "package.json").write_text(json.dumps({
                "scripts": {
                    "build": "vite build",
                    "start:prod": "pm2 start ecosystem.config.js",
                },
            }), encoding="utf-8")
            saved_profile = {
                "project_type": "node",
                "build_policy": "if_missing",
                "runtime_entry": "dist/main.js",
                "auto_install": True,
                "auto_build": True,
            }

            profile = projects._normalize_deployment_profile(saved_profile, tmpdir)

        self.assertEqual(profile["build_policy"], "if_missing")
        self.assertEqual(profile["runtime_entry"], "dist/main.js")
        self.assertTrue(profile["auto_install"])
        self.assertTrue(profile["auto_build"])

    def test_project_file_upload_saves_files_in_current_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = {"name": "svc", "path": tmpdir, "tenant_id": "tenant-a"}
            nested_dir = Path(tmpdir) / "config"
            nested_dir.mkdir()
            user = {"role": "tenant_admin", "tenant_id": "tenant-a"}
            with web_server.app.test_request_context(
                "/api/projects/svc/files",
                method="POST",
                data={
                    "path": "config",
                    "project_files": (io.BytesIO(b"setting=value"), "settings.env"),
                },
                content_type="multipart/form-data",
            ), patch.object(web_server, "_get_authenticated_user", return_value=user), patch.object(
                web_server, "_user_can_manage_projects", return_value=True
            ), patch.object(web_server, "_get_project_for_user", return_value=project):
                response, status = web_server.upload_project_files("svc")

            self.assertEqual(status, 201)
            self.assertEqual((nested_dir / "settings.env").read_bytes(), b"setting=value")

    def test_pm2_service_payload_includes_registry_project_path(self):
        payload = web_server._build_pm2_service_payload(
            {"name": "core-api", "pm2_env": {"status": "online"}, "monit": {}},
            8080,
            "C:/projects/core-api",
        )

        self.assertEqual(payload["path"], "C:/projects/core-api")

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
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(project_runtime, "resolve_executable", return_value=None):
            command, error = project_runtime.prepare_install_command(
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
