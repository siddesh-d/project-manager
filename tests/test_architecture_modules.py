import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from assistant.core import conversation
from assistant.services import pm2_cli, project_runtime


class TestConversation(unittest.TestCase):
    def tearDown(self):
        conversation.set_log_sink(None)
        conversation.set_event_sink(None)

    def test_broadcast_streams_to_sink_and_respects_muted_voice(self):
        sink = Mock()
        conversation.set_log_sink(sink)
        voice = Mock(muted=True)

        conversation.broadcast(voice, "hello", log_type="T", color="c")

        sink.assert_called_once_with("T", "hello", "c")
        voice.speak_async.assert_not_called()

    def test_broadcast_speaks_when_unmuted(self):
        conversation.set_log_sink(Mock())
        voice = Mock(muted=False)

        conversation.broadcast(voice, "hello", wait=True)

        voice.speak_and_wait.assert_called_once_with("hello")

    def test_broadcast_without_sink_prints(self):
        with patch("builtins.print") as printed:
            conversation.broadcast(None, "hello", speak=False)
        printed.assert_called_once()

    def test_submit_reply_without_pending_question_is_not_consumed(self):
        self.assertFalse(conversation.submit_reply("yes"))

    def test_require_confirmation_skips_prompt_for_exact_ui_commands(self):
        self.assertTrue(conversation.require_confirmation(Mock(), None, "stop", "api", is_ui_exact=True))

    def test_require_confirmation_accepts_affirmative_answer(self):
        with patch.object(conversation, "ask_question", return_value="Yes, proceed"):
            self.assertTrue(conversation.require_confirmation(Mock(), None, "stop", "api", is_ui_exact=False))

    def test_require_confirmation_cancels_otherwise(self):
        with patch.object(conversation, "ask_question", return_value=None), \
                patch.object(conversation, "broadcast") as broadcast:
            self.assertFalse(conversation.require_confirmation(Mock(), None, "stop", "api", is_ui_exact=False))
        broadcast.assert_called_once()

    def test_emit_event_forwards_to_sink(self):
        sink = Mock()
        conversation.set_event_sink(sink)
        conversation.emit_event("evt", {"a": 1})
        sink.assert_called_once_with("evt", {"a": 1})


class TestPm2Cli(unittest.TestCase):
    def test_parse_jlist_output_ignores_banner_noise(self):
        output = 'update available\n[{"name": "api"}]\n'
        self.assertEqual(pm2_cli.parse_jlist_output(output), [{"name": "api"}])

    def test_parse_jlist_output_without_payload_is_empty(self):
        self.assertEqual(pm2_cli.parse_jlist_output("nothing here"), [])

    def test_fetch_pm2_processes_returns_none_on_failure(self):
        with patch.object(pm2_cli.subprocess, "run", return_value=Mock(returncode=1, stdout="")):
            self.assertIsNone(pm2_cli.fetch_pm2_processes())
        with patch.object(pm2_cli.subprocess, "run", side_effect=OSError):
            self.assertIsNone(pm2_cli.fetch_pm2_processes())

    def test_resolve_pm2_target_prefers_exact_then_partial_match(self):
        processes = [{"name": "api-gateway"}, {"name": "api"}]
        with patch.object(pm2_cli, "fetch_pm2_processes", return_value=processes):
            self.assertEqual(pm2_cli.resolve_pm2_target("API"), "api")
            self.assertEqual(pm2_cli.resolve_pm2_target("gate"), "api-gateway")
            self.assertEqual(pm2_cli.resolve_pm2_target("missing"), "missing")

    def test_pm2_service_status_reads_matching_process(self):
        processes = [{"name": "api", "pm2_env": {"status": "ONLINE"}}]
        with patch.object(pm2_cli, "fetch_pm2_processes", return_value=processes):
            self.assertEqual(pm2_cli.pm2_service_status("api"), "online")
            self.assertEqual(pm2_cli.pm2_service_status("other"), "")

    def test_missing_module_detection(self):
        self.assertTrue(pm2_cli.looks_like_missing_module_error("Error: Cannot find module 'x'"))
        self.assertFalse(pm2_cli.looks_like_missing_module_error("port in use"))


class TestProjectRuntime(unittest.TestCase):
    def test_build_command_env_dedupes_path_and_appends_extra_bin(self):
        sep = os.pathsep
        with patch.dict(os.environ, {"PATH": sep.join(["/a", "/a", "/b"]), "EXTRA_BIN_PATH": "/c"}):
            env = project_runtime.build_command_env({"FOO": "bar"})
        parts = env["PATH"].split(sep)
        self.assertEqual(parts.count("/a"), 1)
        self.assertLess(parts.index("/b"), parts.index("/c"))
        self.assertEqual(env["FOO"], "bar")

    def test_derive_install_command_prefers_configured_and_lockfiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(project_runtime.derive_install_command(tmpdir, {"install_command": "make deps"}), "make deps")
            self.assertEqual(project_runtime.derive_install_command(tmpdir, {"project_type": "node"}), ["npm", "install"])
            open(os.path.join(tmpdir, "pnpm-lock.yaml"), "w").close()
            self.assertEqual(
                project_runtime.derive_install_command(tmpdir, {"project_type": "node"}),
                ["pnpm", "install", "--frozen-lockfile"],
            )

    def test_validate_project_requirements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = project_runtime.runtime_profile({"deployment_profile": {"project_type": "node", "required_files": ["x.js"]}})
            errors = project_runtime.validate_project_requirements({"path": tmpdir}, profile)
            self.assertIn("Required file missing: x.js", errors)
            self.assertIn("package.json is missing for Node project.", errors)
        missing = project_runtime.validate_project_requirements({"path": os.path.join(tmpdir, "nope")}, profile)
        self.assertEqual(missing, ["Project directory is missing on disk."])

    def test_needs_build_policies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(project_runtime.needs_build(tmpdir, {"build_policy": "never"}, {}))
            self.assertTrue(project_runtime.needs_build(tmpdir, {"build_policy": "always"}, {}))
            self.assertTrue(project_runtime.needs_build(tmpdir, {"build_policy": "if_missing", "runtime_entry": "dist/a.js"}, {}))
            os.makedirs(os.path.join(tmpdir, "dist"))
            open(os.path.join(tmpdir, "dist", "a.js"), "w").close()
            self.assertFalse(project_runtime.needs_build(tmpdir, {"build_policy": "if_missing", "runtime_entry": "dist/a.js"}, {}))

    def test_prepare_install_command_requires_package_json_for_node(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            command, error = project_runtime.prepare_install_command("make deps", "node", tmpdir)
            self.assertIsNone(command)
            self.assertIn("package.json", error)

    def test_load_dotenv_vars_parses_quotes_and_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".env"), "w", encoding="utf-8") as handle:
                handle.write("# c\nA=1\nexport B=\"two\"\nbad line\n")
            self.assertEqual(project_runtime.load_dotenv_vars(tmpdir), {"A": "1", "B": "two"})


if __name__ == "__main__":
    unittest.main()
