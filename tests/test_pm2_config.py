import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


class TestPm2ConfigExternalization(unittest.TestCase):
    def test_pm2_settings_load_from_external_json_and_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "pm2": {
                            "refresh_seconds": 30,
                            "fields": {
                                "uptime": True,
                                "cpu": True,
                                "memory": True,
                                "user": False,
                                "watching": False,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            original_settings_file = os.environ.get("JARVIS_SETTINGS_FILE")
            original_refresh_seconds = os.environ.get("JARVIS_PM2_REFRESH_SECONDS")
            original_user_flag = os.environ.get("JARVIS_PM2_SHOW_USER")
            os.environ["JARVIS_SETTINGS_FILE"] = str(settings_path)
            os.environ["JARVIS_PM2_REFRESH_SECONDS"] = "12"
            os.environ["JARVIS_PM2_SHOW_USER"] = "true"

            try:
                for module_name in ["jarvis_assistant.config.settings", "jarvis_assistant.config"]:
                    sys.modules.pop(module_name, None)

                settings_module = importlib.import_module("jarvis_assistant.config.settings")

                self.assertEqual(settings_module.PM2_TELEMETRY_REFRESH_SECONDS, 12)
                self.assertIs(settings_module.PM2_FIELDS["user"], True)
                self.assertIs(settings_module.PM2_FIELDS["uptime"], True)
                self.assertIs(settings_module.PM2_FIELDS["watching"], False)
                self.assertIn("pm2", settings_module.PM2_CONFIG)
            finally:
                if original_settings_file is None:
                    os.environ.pop("JARVIS_SETTINGS_FILE", None)
                else:
                    os.environ["JARVIS_SETTINGS_FILE"] = original_settings_file

                if original_refresh_seconds is None:
                    os.environ.pop("JARVIS_PM2_REFRESH_SECONDS", None)
                else:
                    os.environ["JARVIS_PM2_REFRESH_SECONDS"] = original_refresh_seconds

                if original_user_flag is None:
                    os.environ.pop("JARVIS_PM2_SHOW_USER", None)
                else:
                    os.environ["JARVIS_PM2_SHOW_USER"] = original_user_flag


if __name__ == "__main__":
    unittest.main()
