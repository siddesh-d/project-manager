import json
import os
import tempfile
import unittest
from pathlib import Path

from jarvis_assistant.core.command_center import _normalize_settings


class TestUiSettingsPreservePm2Config(unittest.TestCase):
    def test_normalize_settings_keeps_pm2_block(self):
        raw = {
            "engine": "browser",
            "mic": False,
            "speaker": True,
            "autolisten": False,
            "voiceURI": "myvoice",
            "volume": 1.0,
            "rate": 1.0,
            "pm2": {
                "refresh_seconds": 15,
                "fields": {
                    "uptime": True,
                    "user": False,
                    "watching": True,
                },
            },
        }

        normalized = _normalize_settings(raw)

        self.assertEqual(normalized["engine"], "browser")
        self.assertEqual(normalized["pm2"]["refresh_seconds"], 15)
        self.assertFalse(normalized["pm2"]["fields"]["user"])
        self.assertTrue(normalized["pm2"]["fields"]["watching"])


if __name__ == "__main__":
    unittest.main()
