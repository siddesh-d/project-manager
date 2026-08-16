import json
import os
import tempfile
import unittest
from pathlib import Path

from jarvis_assistant.core.command_center import _load_settings_file, _persist_settings_file


class TestPersistSettingsKeepsPm2(unittest.TestCase):
    def test_persist_settings_keeps_pm2_block(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "engine": "browser",
                        "mic": False,
                        "speaker": False,
                        "autolisten": False,
                        "voiceURI": "myvoice",
                        "volume": 0.0,
                        "rate": 1.0,
                        "pm2": {
                            "refresh_seconds": 15,
                            "fields": {"uptime": True, "user": False, "watching": True},
                        },
                    }
                ),
                encoding="utf-8",
            )

            original = os.environ.get("JARVIS_SETTINGS_FILE")
            os.environ["JARVIS_SETTINGS_FILE"] = str(settings_path)

            try:
                settings = _load_settings_file()
                settings["mic"] = True
                settings["speaker"] = True
                _persist_settings_file(settings)

                saved = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertIn("pm2", saved)
                self.assertEqual(saved["pm2"]["refresh_seconds"], 15)
                self.assertFalse(saved["pm2"]["fields"]["user"])
            finally:
                if original is None:
                    os.environ.pop("JARVIS_SETTINGS_FILE", None)
                else:
                    os.environ["JARVIS_SETTINGS_FILE"] = original


if __name__ == "__main__":
    unittest.main()
