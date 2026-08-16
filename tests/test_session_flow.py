import unittest

from jarvis_assistant.services.web_server import app


class TestSessionFlow(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_login_and_logout_session_flow(self):
        login_response = self.client.post(
            '/api/login',
            json={'username': 'admin', 'password': 'admin'}
        )
        self.assertEqual(login_response.status_code, 200)
        payload = login_response.get_json()
        self.assertTrue(payload.get('ok'))

        session_response = self.client.get('/api/session')
        self.assertEqual(session_response.status_code, 200)
        session_payload = session_response.get_json()
        self.assertTrue(session_payload.get('authenticated'))

        logout_response = self.client.post('/api/logout')
        self.assertEqual(logout_response.status_code, 200)

        after_logout = self.client.get('/api/session')
        self.assertEqual(after_logout.status_code, 401)


if __name__ == '__main__':
    unittest.main()
