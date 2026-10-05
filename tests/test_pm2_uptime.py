import unittest
from unittest.mock import patch

from assistant.services import web_server


class TestPm2Uptime(unittest.TestCase):
    def test_start_timestamps_use_milliseconds_at_every_process_age(self):
        now = 1_800_000_000
        cases = [
            (0, '0s'),
            (14, '14s'),
            (328, '5m 28s'),
            (999, '16m 39s'),
            (1000, '16m 40s'),
            (10800, '3h'),
            (90061, '1d 1h 1m 1s'),
        ]
        with patch.object(web_server.time, 'time', return_value=now):
            for elapsed, expected in cases:
                for value in [(now - elapsed) * 1000, str((now - elapsed) * 1000)]:
                    with self.subTest(elapsed=elapsed, value=value):
                        self.assertEqual(web_server._format_pm2_uptime(value, timestamp_ms=True), expected)

    def test_future_and_missing_start_timestamps_show_zero(self):
        with patch.object(web_server.time, 'time', return_value=1_800_000_000):
            for value in [None, '', 0, -1, 1_800_000_001_000]:
                with self.subTest(value=value):
                    self.assertEqual(web_server._format_pm2_uptime(value, timestamp_ms=True), '0s')

    def test_duration_fallbacks_do_not_change_units_with_magnitude(self):
        for value, expected in [(328, '5m 28s'), (1_000_000, '11d 13h 46m 40s'),
                                ('10800', '3h'), ('1h 2m 3s', '1h 2m 3s')]:
            with self.subTest(value=value):
                self.assertEqual(web_server._format_pm2_uptime(value), expected)

    def test_regular_and_cluster_payloads_display_elapsed_uptime(self):
        now = 1_800_000_000
        with patch.object(web_server.time, 'time', return_value=now), patch.dict(
            web_server.PM2_FIELDS, {'uptime': True}
        ):
            regular = {'name': 'api', 'pm2_env': {'status': 'online', 'pm_uptime': (now - 328) * 1000}}
            self.assertEqual(web_server._build_pm2_service_payload(regular)['uptime'], '5m 28s')
            workers = [dict(regular), dict(regular)]
            cluster = web_server._group_pm2_processes(workers)['api']
            self.assertEqual(web_server._build_pm2_service_payload(cluster)['uptime'], '5m 28s')
            self.assertEqual(cluster['instances'], 2)

    def test_payload_uses_duration_only_when_start_timestamp_is_absent(self):
        with patch.dict(web_server.PM2_FIELDS, {'uptime': True}):
            for env, expected in [({'uptime': 10800}, '3h'),
                                  ({'pm_uptime': 0, 'uptime': 10800}, '0s')]:
                with self.subTest(env=env):
                    payload = web_server._build_pm2_service_payload({'name': 'api', 'pm2_env': env})
                    self.assertEqual(payload['uptime'], expected)


if __name__ == '__main__':
    unittest.main()