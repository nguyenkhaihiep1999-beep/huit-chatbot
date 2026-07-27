import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        api._request_windows.clear()
        self.client = TestClient(api.app)

    def test_chat_validation_rejects_oversized_question(self):
        response = self.client.post("/api/chat", json={"question": "x" * 801})
        self.assertEqual(response.status_code, 422)

    def test_chat_hides_internal_errors(self):
        with patch.object(api.rag_core, "answer", side_effect=RuntimeError("secret")):
            response = self.client.post("/api/chat", json={"question": "Học phí?"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)

    def test_admin_endpoint_is_closed_without_token_configuration(self):
        with patch.dict(os.environ, {"ADMIN_TOKEN": ""}):
            response = self.client.post("/api/clear-cache")
        self.assertEqual(response.status_code, 503)

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")

    def test_chat_success(self):
        expected = {"answer": "OK", "sources": []}
        with patch.object(api.rag_core, "answer", return_value=expected):
            response = self.client.post("/api/chat", json={"question": "HUIT?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)


if __name__ == "__main__":
    unittest.main()
